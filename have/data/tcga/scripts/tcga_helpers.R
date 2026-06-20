#!/usr/bin/env Rscript
# TCGA data-extraction helper called from the Python agent.
#
# Reads a JSON request from stdin:   {"action": "...", "params": {...}}
# Writes a JSON response to stdout.  Progress / errors go to stderr.
#
# Actions:
#   list_public_data_types  -> enumerate every open-access (category, type,
#                              workflow) combo for a project.
#   download_modality       -> GDCquery + GDCdownload + GDCprepare for one combo.
#   extract_schema          -> describe columns of a downloaded file (.rds,
#                              tabular, MAF, XML).

suppressPackageStartupMessages({
  library(TCGAbiolinks)
  library(jsonlite)
  library(SummarizedExperiment)
})

sanitize <- function(x) {
  if (is.null(x) || is.na(x) || x == "") return("default")
  gsub("[^A-Za-z0-9._-]+", "_", x)
}

describe_cols <- function(df, max_cols = 200) {
  if (ncol(df) == 0) return(list())
  cols <- head(names(df), max_cols)
  lapply(cols, function(nm) {
    v <- df[[nm]]
    if (is.list(v)) v <- vapply(v, function(x) paste(as.character(x), collapse = ";"), character(1))
    nonna <- v[!is.na(v)]
    list(
      name = nm,
      dtype = class(v)[1],
      n_unique = length(unique(nonna)),
      example = head(as.character(nonna), 3)
    )
  })
}

# ---------------------------------------------------------------------------
# Response is written to a Python-provided file path, NOT stdout — because
# TCGAbiolinks' GDCdownload writes a "Downloading: N kB" progress bar straight
# to stdout that would otherwise corrupt our JSON.
RESPONSE_PATH <- NULL

emit <- function(obj) {
  txt <- toJSON(obj, auto_unbox = TRUE, pretty = TRUE, na = "null", null = "null")
  if (is.null(RESPONSE_PATH)) {
    cat(txt); cat("\n")
  } else {
    writeLines(txt, RESPONSE_PATH)
  }
}

log_msg <- function(...) message(sprintf("[R] %s", paste(..., collapse = " ")))

# ---------------------------------------------------------------------------
action_list_public_data_types <- function(params) {
  project <- params$project
  log_msg("listing data categories for", project)
  summary <- getProjectSummary(project)
  cats <- summary$data_categories$data_category
  # Patient (case) count for this project — used downstream as the denominator
  # in per-patient size estimates. Some projects report `case_count`; fall
  # back to NA so Python can apply a heuristic.
  case_count <- if (!is.null(summary$case_count)) as.integer(summary$case_count) else NA_integer_
  log_msg("found", length(cats), "categories;", "case_count =", case_count, ":",
          paste(cats, collapse = " | "))

  results <- list()
  for (cat_name in cats) {
    log_msg("querying category:", cat_name)
    q <- tryCatch(
      GDCquery(project = project, data.category = cat_name),
      error = function(e) { log_msg("  GDCquery failed:", e$message); NULL }
    )
    if (is.null(q)) next
    df <- getResults(q)
    if (nrow(df) == 0) next

    # Some categories use 'analysis_workflow_type', some don't have it.
    wf <- if ("analysis_workflow_type" %in% names(df)) df$analysis_workflow_type else rep(NA, nrow(df))
    df$.workflow <- ifelse(is.na(wf) | wf == "", "__none__", wf)
    df$.format <- if ("data_format" %in% names(df)) df$data_format else "unknown"
    df$.access <- if ("access" %in% names(df)) df$access else "unknown"
    df$.dtype <- if ("data_type" %in% names(df)) df$data_type else "unknown"

    # Keep only open-access rows, then collapse per (data_type, workflow):
    # different data_formats (Biotab vs XML vs Biotab SSF, etc.) downloaded
    # under the same GDCquery, so they belong to one modality.
    df <- df[df$.access == "open", , drop = FALSE]
    if (nrow(df) == 0) next

    keys <- paste(df$.dtype, df$.workflow, sep = "||")
    for (key in unique(keys)) {
      sub <- df[keys == key, , drop = FALSE]
      dtype <- sub$.dtype[1]
      workflow <- sub$.workflow[1]
      results[[length(results) + 1]] <- list(
        data_category = cat_name,
        data_type     = as.character(dtype),
        workflow_type = if (workflow == "__none__") NULL else as.character(workflow),
        data_formats  = sort(unique(as.character(sub$.format))),
        n_files       = nrow(sub)
      )
    }
  }
  log_msg("returning", length(results), "open-access modalities")
  emit(list(project = project, case_count = case_count,
            n_modalities = length(results), modalities = results))
}

# ---------------------------------------------------------------------------
action_download_modality <- function(params) {
  project       <- params$project
  data_category <- params$data_category
  data_type     <- params$data_type
  workflow_type <- params$workflow_type            # may be NULL
  output_root   <- params$output_root
  max_files     <- if (!is.null(params$max_files)) as.integer(params$max_files) else NA_integer_

  # TCGAbiolinks lays files out as
  #   <output_root>/<project>/<data_category_no_spaces>/<data_type_no_spaces>/<file_id>/<file>
  # We pass output_root straight through and reuse its sanitisation for the
  # prepared.rds path.
  cat_san  <- sanitize(data_category)
  type_san <- sanitize(data_type)
  type_dir <- file.path(output_root, project, cat_san, type_san)
  dir.create(type_dir, recursive = TRUE, showWarnings = FALSE)

  qargs <- list(project = project, data.category = data_category,
                data.type = data_type, access = "open")
  if (!is.null(workflow_type) && !is.na(workflow_type) && nzchar(workflow_type)) {
    qargs$workflow.type <- workflow_type
  }
  log_msg("GDCquery:", project, "/", data_category, "/", data_type,
          if (!is.null(workflow_type)) paste("/", workflow_type) else "")
  # TCGAbiolinks rejects data.type values not in its hardcoded whitelist
  # (checkDataTypeInput) even when GDC actually has the data — Pathology Report
  # is one such case. Fall back to querying by category only, then filter the
  # results post-hoc by data_type.
  q <- tryCatch(
    do.call(GDCquery, qargs),
    error = function(e) {
      msg <- conditionMessage(e)
      if (grepl("checkDataTypeInput|data\\.type|wrong data\\.type", msg, ignore.case = TRUE)) {
        log_msg("GDCquery rejected data.type='", data_type,
                "' (not in TCGAbiolinks whitelist); retrying without data.type and filtering post-hoc")
        fb_args <- qargs; fb_args$data.type <- NULL
        # workflow.type is unlikely to be set when data.type whitelist fails,
        # but drop it to be safe — we'll filter post-hoc.
        fb_args$workflow.type <- NULL
        fb_q <- do.call(GDCquery, fb_args)
        # Filter $results[[1]] by data_type (and workflow if requested).
        res <- fb_q$results[[1]]
        if ("data_type" %in% names(res)) {
          res <- res[res$data_type == data_type, , drop = FALSE]
        }
        if (!is.null(workflow_type) && !is.na(workflow_type) && nzchar(workflow_type) &&
            "analysis_workflow_type" %in% names(res)) {
          res <- res[res$analysis_workflow_type == workflow_type, , drop = FALSE]
        }
        if (nrow(res) == 0) {
          stop("post-hoc filter for data_type='", data_type, "' returned 0 files")
        }
        fb_q$results[[1]] <- res
        log_msg("fallback query (filtered) returned", nrow(res), "files")
        fb_q
      } else {
        stop(e)
      }
    }
  )
  total_files <- nrow(getResults(q))
  log_msg("query returned", total_files, "files")

  # Optional cap (TCGA_MAX_FILES) — default 5 in the Python wrapper for fast
  # feasibility tests; pass 0/"unlimited" to disable.
  if (!is.na(max_files) && max_files > 0 && max_files < total_files) {
    log_msg("capping to first", max_files, "files (TCGA_MAX_FILES)")
    q$results[[1]] <- q$results[[1]][seq_len(max_files), , drop = FALSE]
  }

  # Per-modality manifest: file_id <-> patient_id <-> data_type mapping.
  # Written BEFORE GDCdownload so we record intent even if download fails.
  manifest_path <- NA_character_
  manifest_res <- tryCatch({
    sel <- getResults(q)
    cases_raw <- if ("cases" %in% names(sel)) as.character(sel$cases) else
                  rep(NA_character_, nrow(sel))
    # cases can be a comma-separated list of sample barcodes; first entry is
    # enough to recover the 12-char patient barcode (TCGA-XX-YYYY).
    first_case <- vapply(strsplit(cases_raw, ",\\s*"),
                         function(x) if (length(x) == 0) NA_character_ else x[1],
                         character(1))
    patient_id <- substr(first_case, 1, 12)
    mf <- data.frame(
      file_id        = if ("file_id" %in% names(sel)) as.character(sel$file_id) else NA_character_,
      file_name      = if ("file_name" %in% names(sel)) as.character(sel$file_name) else NA_character_,
      patient_id     = patient_id,
      sample_barcode = first_case,
      cases          = cases_raw,
      project        = project,
      data_category  = data_category,
      data_type      = data_type,
      workflow_type  = if (!is.null(workflow_type) && nzchar(workflow_type)) workflow_type else "",
      data_format    = if ("data_format" %in% names(sel)) as.character(sel$data_format) else NA_character_,
      file_size      = if ("file_size" %in% names(sel)) as.character(sel$file_size) else NA_character_,
      md5sum         = if ("md5sum" %in% names(sel)) as.character(sel$md5sum) else NA_character_,
      access         = if ("access" %in% names(sel)) as.character(sel$access) else NA_character_,
      stringsAsFactors = FALSE
    )
    mf_name <- if (!is.null(workflow_type) && !is.na(workflow_type) && nzchar(workflow_type))
      paste0(sanitize(workflow_type), ".manifest.tsv") else "manifest.tsv"
    mp <- file.path(type_dir, mf_name)
    write.table(mf, file = mp, sep = "\t", quote = FALSE,
                row.names = FALSE, na = "")
    log_msg("wrote manifest (", nrow(mf), "rows) ->", mp)
    mp
  }, error = function(e) { log_msg("manifest write failed:", e$message); NA_character_ })
  if (!is.na(manifest_res)) manifest_path <- manifest_res

  dl_status <- tryCatch({
    GDCdownload(q, directory = output_root, method = "api", files.per.chunk = 20)
    "ok"
  }, error = function(e) { log_msg("GDCdownload error:", e$message); paste0("error: ", e$message) })

  prepared_path <- NA_character_
  prepared_class <- NA_character_
  prep_err <- NA_character_
  prepared <- tryCatch(
    GDCprepare(q, directory = output_root, summarizedExperiment = TRUE),
    error = function(e) { prep_err <<- e$message; NULL }
  )
  if (is.null(prepared)) {
    # Fallback: try without SE
    prepared <- tryCatch(
      GDCprepare(q, directory = output_root, summarizedExperiment = FALSE),
      error = function(e) { prep_err <<- paste(prep_err, "|", e$message); NULL }
    )
  }
  if (!is.null(prepared)) {
    prepared_class <- paste(class(prepared), collapse = ",")
    # If there's a workflow_type, name the .rds with it so multiple workflows
    # under the same data_type don't collide. Otherwise just prepared.rds.
    rds_name <- if (!is.null(workflow_type) && !is.na(workflow_type) && nzchar(workflow_type))
      paste0(sanitize(workflow_type), ".prepared.rds") else "prepared.rds"
    prepared_path  <- file.path(type_dir, rds_name)
    saveRDS(prepared, prepared_path)
    log_msg("saved prepared object (", prepared_class, ") ->", prepared_path)
  } else {
    log_msg("GDCprepare failed:", prep_err)
  }

  raw_files <- list.files(type_dir, recursive = TRUE, full.names = TRUE)
  raw_files <- raw_files[!grepl("\\.prepared\\.rds$|/prepared\\.rds$",
                                raw_files, perl = TRUE)]
  emit(list(
    type_dir        = type_dir,
    n_files_listed  = total_files,
    n_files_on_disk = length(raw_files),
    download_status = dl_status,
    prepared_path   = if (is.na(prepared_path)) NULL else prepared_path,
    prepared_class  = if (is.na(prepared_class)) NULL else prepared_class,
    prepare_error   = if (is.na(prep_err)) NULL else prep_err,
    manifest_path   = if (is.na(manifest_path)) NULL else manifest_path,
    sample_raw_files = head(raw_files, 5)
  ))
}

# ---------------------------------------------------------------------------
schema_from_se <- function(obj) {
  schema <- list(
    object_class = paste(class(obj), collapse = ","),
    n_features = nrow(obj),
    n_samples  = ncol(obj),
    assays     = SummarizedExperiment::assayNames(obj)
  )
  cd <- tryCatch(as.data.frame(SummarizedExperiment::colData(obj)),
                 error = function(e) data.frame())
  rd <- tryCatch(as.data.frame(SummarizedExperiment::rowData(obj)),
                 error = function(e) data.frame())
  schema$colData_columns <- describe_cols(cd)
  schema$rowData_columns <- describe_cols(rd)
  schema
}

action_extract_schema <- function(params) {
  file_path <- params$file_path
  if (!file.exists(file_path)) {
    emit(list(file = file_path, error = "file not found")); return(invisible())
  }
  log_msg("extract_schema:", file_path)

  fp_lower <- tolower(file_path)
  if (grepl("\\.rds$", fp_lower)) {
    obj <- readRDS(file_path)
    out <- list(file = file_path, source = "rds")
    if (inherits(obj, "SummarizedExperiment")) {
      out <- c(out, schema_from_se(obj))
    } else if (is.data.frame(obj)) {
      out$object_class <- paste(class(obj), collapse = ",")
      out$n_rows <- nrow(obj); out$n_cols <- ncol(obj)
      out$columns <- describe_cols(obj)
    } else if (is.list(obj)) {
      out$object_class <- paste(class(obj), collapse = ",")
      out$n_elements <- length(obj)
      nms <- names(obj); if (is.null(nms)) nms <- as.character(seq_along(obj))
      # Cap the name dump — clinical lists can contain 500+ per-case XML names.
      out$element_names_sample <- head(nms, 30)
      element_kinds <- vapply(obj, function(x) class(x)[1], character(1))
      out$element_class_counts <- as.list(table(element_kinds))
      # Pick "interesting" tabular elements:
      #   - is a data.frame / tibble
      #   - has > 1 column OR a column name that does not look like raw XML
      # (Clinical Supplement RDS contains 500+ per-case XML tibbles that
      # collapse to a single column with name "<?xml ...>" — skip those.)
      is_xml_blob <- function(d) {
        if (ncol(d) > 1) return(FALSE)
        cn <- names(d)[1]
        if (is.null(cn)) return(FALSE)
        grepl("^<\\?xml", cn) || grepl("^<[a-zA-Z]", cn)
      }
      df_idx <- which(vapply(obj, function(x)
        is.data.frame(x) && !is_xml_blob(x), logical(1)))
      out$n_tabular_elements <- length(df_idx)
      if (length(df_idx) > 0) {
        # unname() so jsonlite emits a JSON array, not a JSON object keyed by index
        out$tabular_elements <- unname(lapply(head(df_idx, 8), function(i) {
          d <- obj[[i]]
          list(name = nms[i], n_rows = nrow(d), n_cols = ncol(d),
               columns = describe_cols(d))
        }))
      }
    } else {
      out$object_class <- paste(class(obj), collapse = ",")
      out$note <- "unsupported R object type"
    }
    emit(out); return(invisible())
  }

  if (grepl("\\.(tsv|txt|maf)(\\.gz)?$", fp_lower) || grepl("\\.csv(\\.gz)?$", fp_lower)) {
    sep <- if (grepl("\\.csv", fp_lower)) "," else "\t"
    df <- tryCatch(
      read.table(file_path, sep = sep, header = TRUE, nrows = 50,
                 comment.char = "#", quote = "", stringsAsFactors = FALSE,
                 fill = TRUE, check.names = FALSE),
      error = function(e) { log_msg("read.table error:", e$message); NULL }
    )
    if (is.null(df)) {
      emit(list(file = file_path, source = "tabular", error = "could not parse"))
      return(invisible())
    }
    emit(list(
      file = file_path, source = "tabular", separator = sep,
      n_cols_sample = ncol(df), n_rows_sample = nrow(df),
      columns = describe_cols(df)
    ))
    return(invisible())
  }

  if (grepl("\\.xml(\\.gz)?$", fp_lower)) {
    txt <- tryCatch(readLines(file_path, n = 200, warn = FALSE),
                    error = function(e) character())
    # crude: extract distinct opening tag names
    tags <- unique(regmatches(txt, gregexpr("<[a-zA-Z_][^ >/]*", txt)))
    tags <- unique(unlist(tags))
    tags <- sub("^<", "", tags)
    emit(list(file = file_path, source = "xml",
              n_distinct_tags_sampled = length(tags),
              sample_tags = head(tags, 60)))
    return(invisible())
  }

  emit(list(file = file_path, source = "unknown",
            note = "no schema extractor for this extension"))
}

# ---------------------------------------------------------------------------
main <- function() {
  # In Rscript, stdin() is the terminal; piped input must be read via the
  # file("stdin") connection. Read the whole thing as one string and parse.
  con <- file("stdin", open = "r")
  on.exit(close(con), add = TRUE)
  lines <- readLines(con, warn = FALSE)
  raw <- paste(lines, collapse = "\n")
  if (!nzchar(raw)) stop("empty stdin: expected a JSON request")
  req <- fromJSON(raw, simplifyVector = FALSE)
  action <- req$action
  params <- req$params
  if (is.null(action)) stop("missing 'action' in request")
  # Optional: caller can ask us to write the JSON response to a file path
  # (avoids collisions with TCGAbiolinks chatter on stdout, e.g. GDCdownload
  # progress lines).
  if (!is.null(req$response_path)) {
    RESPONSE_PATH <<- req$response_path
  }

  switch(action,
    list_public_data_types = action_list_public_data_types(params),
    download_modality      = action_download_modality(params),
    extract_schema         = action_extract_schema(params),
    stop("unknown action: ", action)
  )
}

main()
