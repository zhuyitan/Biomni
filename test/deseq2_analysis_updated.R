
#!R
library(DESeq2)

# Load the expression data with unique row names
expression_data <- read.delim('./data/GSE329088/GSE329088/matrix/GSE329088_series_matrix.txt.gz', row.names=1)
rownames(expression_data) <- make.unique(rownames(expression_data))

# Create a DESeq2 dataset
dds <- DESeqDataSetFromMatrix(countData = expression_data, colData = col_data, design = ~ condition)

# Run the DESeq2 analysis
dds <- DESeq(dds)

# Get results for differential expression
res <- results(dds)

# Save the results
write.csv(as.data.frame(res), file='deseq2_results.csv')
