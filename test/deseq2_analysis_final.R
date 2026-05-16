
#!R
library(DESeq2)

# Load the expression data without row names initially
expression_data <- read.delim('./data/GSE329088/GSE329088/matrix/GSE329088_series_matrix.txt.gz', header=TRUE)
rownames(expression_data) <- make.unique(as.character(expression_data[,1]))
expression_data <- expression_data[,-1]

# Correctly construct col_data to match the expression data samples
sample_names <- colnames(expression_data)
conditions <- rep(c('control', 'treatment'), length.out=length(sample_names))  # Placeholder: adjust according to actual data
col_data <- data.frame(
  row.names = sample_names,
  condition = factor(conditions)
)

# Create a DESeq2 dataset
dds <- DESeqDataSetFromMatrix(countData = expression_data, colData = col_data, design = ~ condition)

# Run the DESeq2 analysis
dds <- DESeq(dds)

# Get results for differential expression
res <- results(dds)

# Save the results
write.csv(as.data.frame(res), file='deseq2_results.csv')
