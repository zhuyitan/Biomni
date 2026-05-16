
#!R
library(DESeq2)

# Load the expression data
expression_data <- read.csv('path/to/expression_data.csv', row.names=1)

# Create a DESeq2 dataset
dds <- DESeqDataSetFromMatrix(countData = expression_data, colData = col_data, design = ~ condition)

# Run the DESeq2 analysis
dds <- DESeq(dds)

# Get results for differential expression
res <- results(dds)

# Save the results
write.csv(as.data.frame(res), file='deseq2_results.csv')
