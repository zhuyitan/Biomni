#!/usr/bin/env Rscript
# Fix R packages that failed due to missing system libraries
# Required conda installs (done before running this):
#   conda install -n biomni_e1 -c conda-forge xz libxml2 libxml2-devel cairo freetype libnetcdf r-xml

options(repos = c(CRAN = "https://cran.rstudio.com/"))

install_if_missing <- function(pkg, bioc = FALSE) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    cat(sprintf("Installing %s...\n", pkg))
    tryCatch({
      if (bioc) {
        BiocManager::install(pkg, ask = FALSE, update = FALSE)
      } else {
        install.packages(pkg, dependencies = TRUE)
      }
      if (requireNamespace(pkg, quietly = TRUE)) {
        cat(sprintf("✓ %s installed\n", pkg))
      } else {
        cat(sprintf("✗ %s FAILED\n", pkg))
      }
    }, error = function(e) {
      cat(sprintf("✗ %s ERROR: %s\n", pkg, conditionMessage(e)))
    })
  } else {
    cat(sprintf("✓ %s already installed\n", pkg))
  }
}

cat("=== Chain 1: Rhtslib → Rsamtools → GenomicAlignments → ShortRead → dada2 ===\n")
install_if_missing("Rhtslib", bioc = TRUE)
install_if_missing("Rsamtools", bioc = TRUE)
install_if_missing("GenomicAlignments", bioc = TRUE)
install_if_missing("ShortRead", bioc = TRUE)
install_if_missing("dada2", bioc = TRUE)

cat("\n=== Chain 2: ncdf4 → mzR → MSnbase → xcms ===\n")
install_if_missing("ncdf4")
install_if_missing("mzR", bioc = TRUE)
install_if_missing("MSnbase", bioc = TRUE)
install_if_missing("xcms", bioc = TRUE)

cat("\n=== Chain 3: gdtools → ggiraph → ggtree → enrichplot → clusterProfiler ===\n")
install_if_missing("gdtools")
install_if_missing("ggiraph")
install_if_missing("ggtree", bioc = TRUE)
install_if_missing("enrichplot", bioc = TRUE)
install_if_missing("clusterProfiler", bioc = TRUE)

cat("\n=== Chain 4: restfulr → rtracklayer → txdbmaker → ensembldb → tximeta ===\n")
install_if_missing("restfulr", bioc = TRUE)
install_if_missing("rtracklayer", bioc = TRUE)
install_if_missing("txdbmaker", bioc = TRUE)
install_if_missing("ensembldb", bioc = TRUE)
install_if_missing("tximeta", bioc = TRUE)

cat("\n=== Chain 5: flowWorkspace → openCyto, ggcyto, flowStats ===\n")
install_if_missing("flowWorkspace", bioc = TRUE)
install_if_missing("openCyto", bioc = TRUE)
install_if_missing("ggcyto", bioc = TRUE)
install_if_missing("flowStats", bioc = TRUE)

cat("\n=== Verification ===\n")
pkgs <- c("Rhtslib","Rsamtools","GenomicAlignments","ShortRead","dada2",
          "ncdf4","mzR","MSnbase","xcms",
          "gdtools","ggiraph","ggtree","enrichplot","clusterProfiler",
          "restfulr","rtracklayer","txdbmaker","ensembldb","tximeta",
          "flowWorkspace","openCyto","ggcyto","flowStats")
for (pkg in pkgs) {
  status <- if (requireNamespace(pkg, quietly=TRUE)) "✓" else "✗"
  cat(sprintf("%s %s\n", status, pkg))
}
cat("\nDone.\n")
