#!/usr/bin/env Rscript
# Comprehensive verification of all R packages from install_r_packages.R

all_pkgs <- c(
  # CRAN packages
  "ggplot2", "lme4", "dplyr", "tidyr", "readr", "stringr", "Matrix", 
  "Rcpp", "devtools", "remotes",
  # Bioconductor packages
  "DESeq2", "limma", "edgeR", "flowCore", "harmony",
  "WGCNA",
  # Previously failed - now fixed
  "Rhtslib", "Rsamtools", "GenomicAlignments", "ShortRead", "dada2",
  "ncdf4", "mzR", "MSnbase", "xcms",
  "gdtools", "ggiraph", "ggtree", "enrichplot", "clusterProfiler",
  "restfulr", "rtracklayer", "txdbmaker", "ensembldb", "tximeta",
  "flowWorkspace", "openCyto", "ggcyto", "flowStats",
  # Other
  "XML", "units"
)

cat("=== R Package Verification ===\n")
ok <- c(); fail <- c()
for (pkg in all_pkgs) {
  status <- if (requireNamespace(pkg, quietly=TRUE)) { ok <<- c(ok, pkg); "✓" } else { fail <<- c(fail, pkg); "✗" }
  cat(sprintf("%s %s\n", status, pkg))
}
cat(sprintf("\n=== Summary: %d/%d installed ===\n", length(ok), length(all_pkgs)))
if (length(fail) > 0) {
  cat("Failed:", paste(fail, collapse=", "), "\n")
}
