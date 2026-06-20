# Data lake dictionary with detailed descriptions (Commercial Mode - Non-commercial datasets commented out)
data_lake_dict = {
    "affinity_capture-ms.parquet": "Protein-protein interactions detected via affinity capture and mass spectrometry.",
    "affinity_capture-rna.parquet": "Protein-RNA interactions detected by affinity capture.",
    # "BindingDB_All_202409.tsv": "Measured binding affinities between proteins and small molecules for drug discovery.",  # Requires commercial license
    "broad_repurposing_hub_molecule_with_smiles.parquet": "Molecules from Broad Institute's Drug Repurposing Hub with SMILES annotations.",
    "broad_repurposing_hub_phase_moa_target_info.parquet": "Drug phases, mechanisms of action, and target information from Broad Institute.",
    "co-fractionation.parquet": "Protein-protein interactions from co-fractionation experiments.",
    "czi_census_datasets_v4.parquet": "Datasets from the Chan Zuckerberg Initiative's Cell Census.",
    "DepMap_CRISPRGeneDependency.csv": "Gene dependency probability estimates for cancer cell lines, including all DepMap models.",
    "DepMap_CRISPRGeneEffect.csv": "Genome-wide CRISPR gene effect estimates for cancer cell lines, including all DepMap models.",
    "DepMap_Model.csv": "Metadata describing all cancer models/cell lines which are referenced by a dataset contained within the DepMap portal.",
    "DepMap_OmicsExpressionProteinCodingGenesTPMLogp1.csv": "Gene expression in TPMs for cancer cell lines, including all DepMap models.",
    # "ddinter_alimentary_tract_metabolism.csv": "Drug-drug interactions for alimentary tract and metabolism drugs from DDInter 2.0 database.",  # CC BY-NC-SA 4.0 - Non-commercial only
    # "ddinter_antineoplastic.csv": "Drug-drug interactions for antineoplastic and immunomodulating agents from DDInter 2.0 database.",  # CC BY-NC-SA 4.0 - Non-commercial only
    # "ddinter_antiparasitic.csv": "Drug-drug interactions for antiparasitic products from DDInter 2.0 database.",  # CC BY-NC-SA 4.0 - Non-commercial only
    # "ddinter_blood_organs.csv": "Drug-drug interactions for blood and blood forming organs drugs from DDInter 2.0 database.",  # CC BY-NC-SA 4.0 - Non-commercial only
    # "ddinter_dermatological.csv": "Drug-drug interactions for dermatological drugs from DDInter 2.0 database.",  # CC BY-NC-SA 4.0 - Non-commercial only
    # "ddinter_hormonal.csv": "Drug-drug interactions for systemic hormonal preparations from DDInter 2.0 database.",  # CC BY-NC-SA 4.0 - Non-commercial only
    # "ddinter_respiratory.csv": "Drug-drug interactions for respiratory system drugs from DDInter 2.0 database.",  # CC BY-NC-SA 4.0 - Non-commercial only
    # "ddinter_various.csv": "Drug-drug interactions for various drugs from DDInter 2.0 database.",  # CC BY-NC-SA 4.0 - Non-commercial only
    # "DisGeNET.parquet": "Gene-disease associations from multiple sources.",  # CC BY-NC-SA 4.0 - Non-commercial only
    "dosage_growth_defect.parquet": "Gene dosage changes affecting growth.",
    # "enamine_cloud_library_smiles.pkl": "Compounds from Enamine REAL library with SMILES annotations.",  # Proprietary - Requires license
    # "evebio_assay_table.csv": "Assay metadata with one row per assay from EveBio pharmome mapping.",  # Proprietary - Requires permission
    # "evebio_bundle_table.csv": "Target subfamily bundles used for screening-to-profiling progression.",  # Proprietary - Requires permission
    # "evebio_compound_table.csv": "Compound metadata with common identifiers from EveBio screening.",  # Proprietary - Requires permission
    # "evebio_control_table.csv": "Control datapoints for all screening and profiling plates.",  # Proprietary - Requires permission
    # "evebio_detailed_result_table.csv": "Expanded results on evebio_summary_result_table with curve fit parameters and phase categories.",  # Proprietary - Requires permission
    # "evebio_observed_points_table.csv": "Raw observed datapoints from all screening and profiling experiments.",  # Proprietary - Requires permission
    # "evebio_summary_result_table.csv": "Succinct summary of results for each assay-compound combination.",  # Proprietary - Requires permission
    # "evebio_target_table.csv": "Target metadata with common identifiers from EveBio screening.",  # Proprietary - Requires permission
    "genebass_missense_LC_filtered.pkl": "Filtered missense variants from GeneBass.",
    "genebass_pLoF_filtered.pkl": "Predicted loss-of-function variants from GeneBass.",
    "genebass_synonymous_filtered.pkl": "Filtered synonymous variants from GeneBass.",
    "gene_info.parquet": "Comprehensive gene information.",
    "genetic_interaction.parquet": "Genetic interactions between genes.",
    "go-plus.json": "Gene ontology data for functional gene annotations.",
    "gtex_tissue_gene_tpm.parquet": "Gene expression (TPM) across human tissues from GTEx.",
    "gwas_catalog.pkl": "Genome-wide association studies (GWAS) results.",
    "hp.obo": "Official HPO release in obographs format",
    "kg.csv": "Precision medicine knowledge graph with 17,080 diseases and 4+ million relationships across biological scales.",
    "marker_celltype.parquet": "Cell type marker genes for identification.",
    # "McPAS-TCR.parquet": "T-cell receptor sequences and specificity data from McPAS database.",  # CC BY-NC-SA 4.0 - Non-commercial only
    # "miRDB_v6.0_results.parquet": "Predicted microRNA targets from miRDB.",  # Non-commercial use only
    # "miRTarBase_microRNA_target_interaction.parquet": "Experimentally validated microRNA-target interactions from miRTarBase.",  # CC BY-NC 4.0 - Non-commercial only
    # "miRTarBase_microRNA_target_interaction_pubmed_abtract.txt": "PubMed abstracts for microRNA-target interactions in miRTarBase.",  # CC BY-NC 4.0 - Non-commercial only
    # "miRTarBase_MicroRNA_Target_Sites.parquet": "Binding sites of microRNAs on target genes from miRTarBase.",  # CC BY-NC 4.0 - Non-commercial only
    "mousemine_m1_positional_geneset.parquet": "Positional gene sets from MouseMine.",
    "mousemine_m2_curated_geneset.parquet": "Curated gene sets from MouseMine.",
    "mousemine_m3_regulatory_target_geneset.parquet": "Regulatory target gene sets from MouseMine.",
    "mousemine_m5_ontology_geneset.parquet": "Ontology-based gene sets from MouseMine.",
    "mousemine_m8_celltype_signature_geneset.parquet": "Cell type signature gene sets from MouseMine.",
    "mousemine_mh_hallmark_geneset.parquet": "Hallmark gene sets from MouseMine.",
    # "msigdb_human_c1_positional_geneset.parquet": "Human positional gene sets from MSigDB.",  # Requires commercial license
    # "msigdb_human_c2_curated_geneset.parquet": "Curated human gene sets from MSigDB.",  # Requires commercial license
    # "msigdb_human_c3_regulatory_target_geneset.parquet": "Regulatory target gene sets from MSigDB.",  # Requires commercial license
    # "msigdb_human_c3_subset_transcription_factor_targets_from_GTRD.parquet": "Transcription factor targets from GTRD/MSigDB.",  # Requires commercial license
    # "msigdb_human_c4_computational_geneset.parquet": "Computationally derived gene sets from MSigDB.",  # Requires commercial license
    # "msigdb_human_c5_ontology_geneset.parquet": "Ontology-based gene sets from MSigDB.",  # Requires commercial license
    # "msigdb_human_c6_oncogenic_signature_geneset.parquet": "Oncogenic signatures from MSigDB.",  # Requires commercial license
    # "msigdb_human_c7_immunologic_signature_geneset.parquet": "Immunologic signatures from MSigDB.",  # Requires commercial license
    # "msigdb_human_c8_celltype_signature_geneset.parquet": "Cell type signatures from MSigDB.",  # Requires commercial license
    # "msigdb_human_h_hallmark_geneset.parquet": "Hallmark gene sets from MSigDB.",  # Requires commercial license
    # "omim.parquet": "Genetic disorders and associated genes from OMIM.",  # Requires commercial license
    "proteinatlas.tsv": "Protein expression data from Human Protein Atlas.",
    "proximity_label-ms.parquet": "Protein interactions via proximity labeling and mass spectrometry.",
    "reconstituted_complex.parquet": "Protein complexes reconstituted in vitro.",
    "sgRNA_KO_SP_mouse.txt": "sgRNA knockout data for mouse.",
    "sgRNA_KO_SP_human.txt": "sgRNA knockout data for human.",
    "synthetic_growth_defect.parquet": "Synthetic growth defects from genetic interactions.",
    "synthetic_lethality.parquet": "Synthetic lethal interactions.",
    "synthetic_rescue.parquet": "Genetic interactions rescuing phenotypes.",
    "two-hybrid.parquet": "Protein-protein interactions detected by yeast two-hybrid assays.",
    "variant_table.parquet": "Annotated genetic variants table.",
    "Virus-Host_PPI_P-HIPSTER_2020.parquet": "Virus-host protein-protein interactions from P-HIPSTER.",
    "txgnn_name_mapping.pkl": "Name mapping for TXGNN.",
    "txgnn_prediction.pkl": "Prediction data for TXGNN.",
    # === TCGA pan-cancer multi-omics (assembled across all cancer types) ===
    # TCGA is open-access for commercial reuse — same entries as env_desc.py.
    # All tcga_* files are local symlinks under data_lake/; nothing is fetched on demand.
    "tcga_data_description.md": "**READ FIRST for any TCGA question.** Authoritative schema for every tcga_* file in the data lake — exact column names, value semantics, join keys, shapes, and matrix↔metadata pairings. Covers TCGA pan-cancer multi-omics (CNV, gene expression, miRNA, DNA methylation on 27K/450K/EPIC v2, RPPA, somatic mutations).",
    "tcga_ge_star.tpm_unstranded.parquet": "TCGA pan-cancer gene expression — STAR TPM, unstranded. 60,660 genes × (3 gene-info cols + 11,505 sample cols). First 3 cols: gene_id (Ensembl), gene_name (HGNC), gene_type. Remaining columns are file_uuid headers — join to tcga_ge_star.metadata.txt on file_uuid for cancer_type, sample_barcode, is_tumor, etc.",
    "tcga_ge_star.metadata.txt": "TCGA gene-expression sample metadata. One row per file_uuid; 15 base columns (cancer_type, study_name, patient_barcode, sample_barcode, sample_type, is_tumor, is_normal, is_metastatic, workflow_type, md5sum, …). Pairs with tcga_ge_star.tpm_unstranded.parquet on file_uuid.",
    "tcga_cnv_ascat3.copy_number.parquet": "TCGA pan-cancer gene-level somatic copy number from ASCAT3 (tumor-purity-corrected absolute integer CN). 60,623 genes × (5 gene-info cols + 10,632 sample cols). Gene-info cols: gene_id, gene_name, chromosome, start, end. Sample columns are file_uuid headers (Int16): 2 = diploid, 0 = homozygous deletion, ≥3 = gain. Join to tcga_cnv_ascat3.metadata.txt on file_uuid.",
    "tcga_cnv_ascat3.metadata.txt": "TCGA CNV sample metadata. One row per file_uuid; 15 base columns including matched_normal_barcode (populated for CNV). Pairs with tcga_cnv_ascat3.copy_number.parquet.",
    "tcga_mirna_bcgsc.reads_per_million.parquet": "TCGA pan-cancer miRNA expression in reads per million mapped (BCGSC pipeline). 1,881 miRNAs × (1 feature col + 11,442 sample cols). Feature col: miRNA_ID (mirBase v21 mature miRNA name, e.g., hsa-let-7a-1). Sample columns are file_uuid headers (float32). Join to tcga_mirna_bcgsc.metadata.txt on file_uuid.",
    "tcga_mirna_bcgsc.metadata.txt": "TCGA miRNA sample metadata. One row per file_uuid; standard 15 base columns. Pairs with tcga_mirna_bcgsc.reads_per_million.parquet.",
    "tcga_dnam_sesame_27k.beta_value.parquet": "TCGA DNA methylation β-values, Illumina HM27 platform (SeSAMe pipeline). 27,578 probes × (1 feature col + 2,663 sample cols). Feature col: IlmnID. Sample columns are file_uuid headers (float32, β in [0,1]; NaN = probe missing on this file's array). Join to tcga_dnam_sesame.metadata.txt on file_uuid (filter array_platform == '27K'); join probes to tcga_annotation_dnam_27k.txt on IlmnID for gene/TSS/CpG-island context.",
    "tcga_dnam_sesame_450k.beta_value.parquet": "TCGA DNA methylation β-values, Illumina HM450 platform (SeSAMe pipeline). 486,427 probes × (1 feature col + 9,812 sample cols). Feature col: IlmnID. Sample columns are file_uuid headers (float32). Join to tcga_dnam_sesame.metadata.txt on file_uuid (filter array_platform == '450K'); join probes to tcga_annotation_dnam_450k.txt on IlmnID.",
    "tcga_dnam_sesame_epic_v2.beta_value.parquet": "TCGA DNA methylation β-values, Illumina EPIC v2 platform (LUAD only). 930,659 probes × (1 feature col + 53 sample cols). Feature col: IlmnID (bare CG ID, e.g., cg25324105). Sample columns are file_uuid headers (float32). Join to tcga_dnam_sesame.metadata.txt on file_uuid (filter array_platform == 'EPIC v2'); join probes to tcga_annotation_dnam_epic_v2.txt on IlmnID.",
    "tcga_dnam_sesame.metadata.txt": "TCGA DNA-methylation sample metadata. One row per file_uuid; 15 base columns plus array_platform ('27K' / '450K' / 'EPIC v2'). Pairs with all three tcga_dnam_sesame_*.beta_value.parquet matrices — filter on array_platform to subset.",
    "tcga_rppa.protein_expression.parquet": "TCGA RPPA protein abundance (MD Anderson). 487 antibodies × (1 feature col + 7,906 sample cols). Feature col: peptide_target (antibody name, e.g., AKT_pT308, 1433BETA). Sample columns are file_uuid headers (float32, approximately log2-ratio scale, mean ~0). Join to tcga_rppa.metadata.txt on file_uuid; join to tcga_annotation_rppa.txt on peptide_target for gene_symbol / entrez_gene_id / uniprot_id mapping.",
    "tcga_rppa.metadata.txt": "TCGA RPPA sample metadata. One row per file_uuid; standard 15 base columns. Pairs with tcga_rppa.protein_expression.parquet.",
    "tcga_mutation.maf.parquet": "TCGA pan-cancer somatic mutations in long format (GDC MAF v1.0). 2,570,542 variant rows × 140 cols. Each row is one variant call in one tumor sample. Key cols: Hugo_Symbol, Chromosome, Start_Position, End_Position, Variant_Classification (18 standard MAF classes), Variant_Type, Tumor_Sample_UUID, Tumor_Sample_Barcode, HGVSp_Short, Consequence, IMPACT, t_depth / t_alt_count, gnomAD_AF, callers (semicolon list). Join to tcga_mutation.metadata.txt on Tumor_Sample_UUID for cancer_type, patient_barcode, etc.",
    "tcga_mutation.gene_by_case.parquet": "TCGA mutation count matrix, gene × case. 19,788 genes × (2 gene-label cols + 10,549 case cols). First 2 cols: Hugo_Symbol, Entrez_Gene_Id. Case columns are '<tumor_barcode>, <normal_barcode>' headers (matches the `case` column in tcga_mutation.metadata.txt). Cell value = count of high-impact protein-changing mutations in that gene/case across 9 Variant_Classifications (Missense, Nonsense, Frame_Shift_Del/Ins, Splice_Site, In_Frame_Del/Ins, Translation_Start_Site, Nonstop). Silent / intron / UTR mutations are NOT counted.",
    "tcga_mutation.mutation_by_case.parquet": "TCGA binary mutation × case matrix. 2,222,181 unique mutations × (48 description cols + 10,549 case cols). Rows are unique mutations identified by 7-tuple (Chromosome, Start_Position, End_Position, Strand, Reference_Allele, Tumor_Seq_Allele1, Tumor_Seq_Allele2). First 48 cols are mutation descriptors (Hugo_Symbol, HGVSp_Short, Consequence, IMPACT, BIOTYPE, CANONICAL, COSMIC, hotspot, …); case columns are '<tumor>, <normal>' headers with 0/1 values. ~99.989% sparse. Join cases to tcga_mutation.metadata.txt on the `case` column.",
    "tcga_mutation.metadata.txt": "TCGA mutation case metadata. One row per file_uuid; 15 base columns plus `case` ('<tumor_barcode>, <normal_barcode>') and Tumor_Sample_UUID. `case` column matches the case-column headers in tcga_mutation.mutation_by_case.parquet and tcga_mutation.gene_by_case.parquet; Tumor_Sample_UUID is the primary join key into tcga_mutation.maf.parquet.",
    "tcga_annotation_dnam_27k.txt": "Illumina HM27 methylation probe annotation, 27,578 rows × 34 cols. Join to tcga_dnam_sesame_27k.beta_value.parquet on IlmnID. Key cols: Gene_ID (Entrez), Symbol, Synonym, Accession, Distance_to_TSS (signed int), TSS_group (derived: TSS200 / TSS1500 / empty), CPG_ISLAND, CPG_ISLAND_LOCATIONS. Controls included with `ctl_` IlmnID prefix.",
    "tcga_annotation_dnam_450k.txt": "Illumina HM450 methylation probe annotation. 807,704 rows for 486,427 unique probes (multi-gene probes exploded into one row per probe-gene pair). Join to tcga_dnam_sesame_450k.beta_value.parquet on IlmnID. Key cols: CHR + MAPINFO (GRCh37), UCSC_RefGene_Name, UCSC_RefGene_Accession, UCSC_RefGene_Group (TSS200 / TSS1500 / 5'UTR / 1stExon / Body / 3'UTR), UCSC_CpG_Islands_Name, Relation_to_UCSC_CpG_Island (Island / N_Shore / S_Shore / …), Enhancer, Phantom, DMR, DHS.",
    "tcga_annotation_dnam_epic_v2.txt": "Illumina EPIC v2 methylation probe annotation. 1,894,457 rows for 930,659 unique probes (multi-gene exploded). Join to tcga_dnam_sesame_epic_v2.beta_value.parquet on IlmnID. Schema close to HM450 plus GencodeV41, Phantom5 enhancers, ENCODE CisReg sites, OpenChromatin. Col 1 (IlmnID) is the bare CG ID to match the data matrix; col 2 (Name) holds the original replicate-suffixed Illumina ID (e.g., cg25324105_BC11).",
    "tcga_annotation_rppa.txt": "TCGA RPPA antibody annotation, 545 rows × 13 cols. Join to tcga_rppa.protein_expression.parquet on peptide_target. Key cols: gene_symbol, entrez_gene_id, uniprot_id (multi-gene antibodies exploded — e.g., pan-AKT → AKT1/AKT2/AKT3), rrid, validation_status (Valid / Caution / …), vendor, species, protein_name_official, annotation_source. 22 of 487 antibodies are UNMATCHED with empty gene columns.",
}

# Updated library_content as a dictionary with detailed descriptions
library_content_dict = {
    # === PYTHON PACKAGES ===
    # Core Bioinformatics Libraries (Python)
    "biopython": "[Python Package] A set of tools for biological computation including parsers for bioinformatics files, access to online services, and interfaces to common bioinformatics programs.",
    "biom-format": "[Python Package] The Biological Observation Matrix (BIOM) format is designed for representing biological sample by observation contingency tables with associated metadata.",
    "scanpy": "[Python Package] A scalable toolkit for analyzing single-cell gene expression data, specifically designed for large datasets using AnnData.",
    "scikit-bio": "[Python Package] Data structures, algorithms, and educational resources for bioinformatics, including sequence analysis, phylogenetics, and ordination methods.",
    "anndata": "[Python Package] A Python package for handling annotated data matrices in memory and on disk, primarily used for single-cell genomics data.",
    "mudata": "[Python Package] A Python package for multimodal data storage and manipulation, extending AnnData to handle multiple modalities.",
    "pyliftover": "[Python Package] A Python implementation of UCSC liftOver tool for converting genomic coordinates between genome assemblies.",
    "biopandas": "[Python Package] A package that provides pandas DataFrames for working with molecular structures and biological data.",
    "biotite": "[Python Package] A comprehensive library for computational molecular biology, providing tools for sequence analysis, structure analysis, and more.",
    "lazyslide": "[Python Package] A Python framework that brings interoperable, reproducible whole slide image analysis, enabling seamless histopathology workflows from preprocessing to deep learning.",
    # Genomics & Variant Analysis (Python)
    "gget": "[Python Package] A toolkit for accessing genomic databases and retrieving sequences, annotations, and other genomic data.",
    "lifelines": "[Python Package] A complete survival analysis library for fitting models, plotting, and statistical tests.",
    # "scvi-tools": "[Python Package] A package for probabilistic modeling of single-cell omics data, including deep generative models.",
    "gseapy": "[Python Package] A Python wrapper for Gene Set Enrichment Analysis (GSEA) and visualization.",
    "scrublet": "[Python Package] A tool for detecting doublets in single-cell RNA-seq data.",
    "cellxgene-census": "[Python Package] A tool for accessing and analyzing the CellxGene Census, a collection of single-cell datasets. To download a dataset, use the download_source_h5ad function with the dataset id as the argument (856c1b98-5727-49da-bf0f-151bdb8cb056, no .h5ad extension).",
    "hyperopt": "[Python Package] A Python library for optimizing hyperparameters of machine learning algorithms.",
    "scvelo": "[Python Package] A tool for RNA velocity analysis in single cells using dynamical models.",
    "pysam": "[Python Package] A Python module for reading, manipulating and writing genomic data sets in SAM/BAM/VCF/BCF formats.",
    "pyfaidx": "[Python Package] A Python package for efficient random access to FASTA files.",
    "pyranges": "[Python Package] A Python package for interval manipulation with a pandas-like interface.",
    "pybedtools": "[Python Package] A Python wrapper for Aaron Quinlan's BEDTools programs.",
    # "panhumanpy": "A Python package for hierarchical, cross-tissue cell type annotation of human single-cell RNA-seq data",
    # Structural Biology & Drug Discovery (Python)
    "rdkit": "[Python Package] A collection of cheminformatics and machine learning tools for working with chemical structures and drug discovery.",
    "deeppurpose": "[Python Package] A deep learning library for drug-target interaction prediction and virtual screening.",
    "pyscreener": "[Python Package] A Python package for virtual screening of chemical compounds.",
    "openbabel": "[Python Package] A chemical toolbox designed to speak the many languages of chemical data, supporting file format conversion and molecular modeling.",
    "descriptastorus": "[Python Package] A library for computing molecular descriptors for machine learning applications in drug discovery.",
    # "pymol": "[Python Package] A molecular visualization system for rendering and animating 3D molecular structures.",
    "openmm": "[Python Package] A toolkit for molecular simulation using high-performance GPU computing.",
    "pytdc": "[Python Package] A Python package for Therapeutics Data Commons, providing access to machine learning datasets for drug discovery.",
    # Data Science & Statistical Analysis (Python)
    "pandas": "[Python Package] A fast, powerful, and flexible data analysis and manipulation library for Python.",
    "numpy": "[Python Package] The fundamental package for scientific computing with Python, providing support for arrays, matrices, and mathematical functions.",
    "scipy": "[Python Package] A Python library for scientific and technical computing, including modules for optimization, linear algebra, integration, and statistics.",
    "scikit-learn": "[Python Package] A machine learning library featuring various classification, regression, and clustering algorithms.",
    "matplotlib": "[Python Package] A comprehensive library for creating static, animated, and interactive visualizations in Python.",
    "seaborn": "[Python Package] A statistical data visualization library based on matplotlib with a high-level interface for drawing attractive statistical graphics.",
    "statsmodels": "[Python Package] A Python module for statistical modeling and econometrics, including descriptive statistics and estimation of statistical models.",
    "pymc3": "[Python Package] A Python package for Bayesian statistical modeling and probabilistic machine learning.",
    # "pystan": "[Python Package] A Python interface to Stan, a platform for statistical modeling and high-performance statistical computation.",
    "umap-learn": "[Python Package] Uniform Manifold Approximation and Projection, a dimension reduction technique.",
    "faiss-cpu": "[Python Package] A library for efficient similarity search and clustering of dense vectors.",
    "harmony-pytorch": "[Python Package] A PyTorch implementation of the Harmony algorithm for integrating single-cell data.",
    # General Bioinformatics & Computational Utilities (Python)
    "tiledb": "[Python Package] A powerful engine for storing and analyzing large-scale genomic data.",
    "tiledbsoma": "[Python Package] A library for working with the SOMA (Stack of Matrices) format using TileDB.",
    "h5py": "[Python Package] A Python interface to the HDF5 binary data format, allowing storage of large amounts of numerical data.",
    "tqdm": "[Python Package] A fast, extensible progress bar for loops and CLI applications.",
    "joblib": "[Python Package] A set of tools to provide lightweight pipelining in Python, including transparent disk-caching and parallel computing.",
    "opencv-python": "[Python Package] OpenCV library for computer vision tasks, useful for image analysis in biological contexts.",
    "PyPDF2": "[Python Package] A library for working with PDF files, useful for extracting text from scientific papers.",
    "googlesearch-python": "[Python Package] A library for performing Google searches programmatically.",
    "scikit-image": "[Python Package] A collection of algorithms for image processing in Python.",
    "pymed": "[Python Package] A Python library for accessing PubMed articles.",
    "arxiv": "[Python Package] A Python wrapper for the arXiv API, allowing access to scientific papers.",
    "scholarly": "[Python Package] A module to retrieve author and publication information from Google Scholar.",
    "cryosparc-tools": "[Python Package] Tools for working with cryoSPARC, a platform for cryo-EM data processing.",
    "mageck": "[Python Package] Analysis of CRISPR screen data.",
    "igraph": "[Python Package] Network analysis and visualization.",
    "pyscenic": "[Python Package] Analysis of single-cell RNA-seq data and gene regulatory networks.",
    "cooler": "[Python Package] Storage and analysis of Hi-C data.",
    "trackpy": "[Python Package] Particle tracking in images and video.",
    # "flowcytometrytools": "[Python Package] Analysis and visualization of flow cytometry data.",
    "cellpose": "[Python Package] Cell segmentation in microscopy images.",
    "viennarna": "[Python Package] RNA secondary structure prediction.",
    "PyMassSpec": "[Python Package] Mass spectrometry data analysis.",
    "python-libsbml": "[Python Package] Working with SBML files for computational biology.",
    "cobra": "[Python Package] Constraint-based modeling of metabolic networks.",
    "reportlab": "[Python Package] Creation of PDF documents.",
    "flowkit": "[Python Package] Toolkit for processing flow cytometry data.",
    "hmmlearn": "[Python Package] Hidden Markov model analysis.",
    "msprime": "[Python Package] Simulation of genetic variation.",
    "tskit": "[Python Package] Handling tree sequences and population genetics data.",
    "cyvcf2": "[Python Package] Fast parsing of VCF files.",
    "pykalman": "[Python Package] Kalman filter and smoother implementation.",
    "fanc": "[Python Package] Analysis of chromatin conformation data.",
    "loompy": "A Python implementation of the Loom file format for efficiently storing and working with large omics datasets.",
    "pyBigWig": "A Python library for accessing bigWig and bigBed files for genome browser track data.",
    "pymzml": "A Python module for high-throughput bioinformatics analysis of mass spectrometry data.",
    "optlang": "A Python package for modeling optimization problems symbolically.",
    "FlowIO": "A Python package for reading and writing flow cytometry data files.",
    "FlowUtils": "Utilities for processing and analyzing flow cytometry data.",
    "arboreto": "A Python package for inferring gene regulatory networks from single-cell RNA-seq data.",
    "pdbfixer": "A Python package for fixing problems in PDB files in preparation for molecular simulations.",
    # === R PACKAGES ===
    # Core R Packages for Data Analysis
    "ggplot2": "[R Package] A system for declaratively creating graphics, based on The Grammar of Graphics. Use with subprocess.run(['Rscript', '-e', 'library(ggplot2); ...']).",
    "dplyr": "[R Package] A grammar of data manipulation, providing a consistent set of verbs that help you solve the most common data manipulation challenges. Use with subprocess.",
    "tidyr": "[R Package] A package that helps you create tidy data, where each column is a variable, each row is an observation, and each cell is a single value. Use with subprocess.",
    "readr": "[R Package] A fast and friendly way to read rectangular data like CSV, TSV, and FWF. Use with subprocess.run(['Rscript', '-e', 'library(readr); ...']).",
    "stringr": "[R Package] A cohesive set of functions designed to make working with strings as easy as possible. Use with subprocess calls.",
    "Matrix": "[R Package] A package that provides classes and methods for dense and sparse matrices. Required for Seurat. Use with subprocess calls.",
    # "Rcpp": "[R Package] Seamless R and C++ Integration, allowing R functions to call compiled C++ code. Use with subprocess calls.",
    # "devtools": "[R Package] Tools to make developing R packages easier, including functions to install packages from GitHub. Use with subprocess calls.",
    # "remotes": "[R Package] Install R packages from GitHub, GitLab, Bitbucket, or other remote repositories. Use with subprocess calls.",
    # Bioinformatics R Packages
    "DESeq2": "[R Package] Differential gene expression analysis based on the negative binomial distribution. Use with subprocess.run(['Rscript', '-e', 'library(DESeq2); ...']).",
    "clusterProfiler": "[R Package] A package for statistical analysis and visualization of functional profiles for genes and gene clusters. Use with subprocess calls.",
    # "DADA2": "[R Package] A package for modeling and correcting Illumina-sequenced amplicon errors. Use with subprocess calls.",
    # "xcms": "[R Package] A package for processing and visualization of LC-MS and GC-MS data. Use with subprocess calls.",
    # "FlowCore": "[R Package] Basic infrastructure for flow cytometry data. Use with subprocess calls.",
    "edgeR": "[R Package] Empirical Analysis of Digital Gene Expression Data in R, for differential expression analysis. Use with subprocess calls.",
    "limma": "[R Package] Linear Models for Microarray Data, for differential expression analysis. Use with subprocess calls.",
    "harmony": "[R Package] A method for integrating and analyzing single-cell data across datasets. Use with subprocess calls.",
    "WGCNA": "[R Package] Weighted Correlation Network Analysis for studying biological networks. Use with subprocess calls.",
    "TCGAbiolinks": "[R Package] Bioconductor package to query, download, and prepare TCGA/GDC data (clinical, mRNA-seq, miRNA, methylation, mutations, CNV) for any TCGA project (e.g. TCGA-LUAD, TCGA-BRCA). For workflow.type use current GDC values like 'STAR - Counts' (NOT the deprecated 'HTSeq - Counts'). Standard workflow: query <- GDCquery(project=..., data.category='Transcriptome Profiling', data.type='Gene Expression Quantification', workflow.type='STAR - Counts', barcode=c(...)); GDCdownload(query); data <- GDCprepare(query); then assay(data, 'unstranded'|'tpm_unstrand'|'fpkm_unstrand'). IMPORTANT: always invoke R via the conda env's Rscript, not bare 'Rscript' (which may resolve to /usr/bin/Rscript without TCGAbiolinks). Use: import sys, os, subprocess; rscript = os.path.join(sys.prefix, 'bin', 'Rscript'); subprocess.run([rscript, '-e', 'library(TCGAbiolinks); ...']).",
    # === CLI TOOLS ===
    # Sequence Analysis Tools
    "samtools": "[CLI Tool] A suite of programs for interacting with high-throughput sequencing data. Use with subprocess.run(['samtools', ...]).",
    "bowtie2": "[CLI Tool] An ultrafast and memory-efficient tool for aligning sequencing reads to long reference sequences. Use with subprocess.run(['bowtie2', ...]).",
    "bwa": "[CLI Tool] Burrows-Wheeler Aligner for mapping low-divergent sequences against a large reference genome. Use with subprocess.run(['bwa', ...]).",
    "bedtools": "[CLI Tool] A powerful toolset for genome arithmetic, allowing operations like intersect, merge, count, and complement on genomic features. Use with subprocess.run(['bedtools', ...]).",
    "macs2": "[CLI Tool] Model-based Analysis of ChIP-Seq data, a tool for identifying transcript factor binding sites.",
    # Quality Control and Processing Tools
    "fastqc": "[CLI Tool] A quality control tool for high throughput sequence data. Use with subprocess.run(['fastqc', ...]).",
    "trimmomatic": "[CLI Tool] A flexible read trimming tool for Illumina NGS data. Use with subprocess.run(['trimmomatic', ...]).",
    # Multiple Sequence Alignment and Phylogenetics
    "mafft": "[CLI Tool] A multiple sequence alignment program for unix-like operating systems. Use with subprocess.run(['mafft', ...]).",
    "Homer": "[CLI Tool] Motif discovery and next-gen sequencing analysis.",
    "FastTree": "[CLI Tool] Phylogenetic trees from sequence alignments.",
    "muscle": "[CLI Tool] Multiple sequence alignment tool.",
    # Genetic Analysis Tools
    "plink": "[CLI Tool] A comprehensive toolkit for genome association studies that can perform a range of large-scale analyses in a computationally efficient manner. Use with subprocess.run(['plink', ...]).",
    "plink2": "[CLI Tool] A comprehensive toolkit for genome association studies that can perform a range of large-scale analyses in a computationally efficient manner. Use with subprocess.run(['plink2', ...]).",
    "gcta64": "[CLI Tool] Genome-wide Complex Trait Analysis (GCTA) tool for estimating the proportion of phenotypic variance explained by genome-wide SNPs and analyzing genetic relationships. Use with subprocess.run(['gcta64', ...]).",
    "iqtree2": "[CLI Tool] An efficient phylogenetic software for maximum likelihood analysis with built-in model selection and ultrafast bootstrap. Use with subprocess.run(['iqtree2', ...]).",
    "ADFR": "AutoDock for Receptors suite for molecular docking and virtual screening. ",
    "diamond": "A sequence aligner for protein and translated DNA searches, designed for high performance analysis of big sequence data. ",
    "fcsparser": "A command-line tool for parsing and analyzing flow cytometry standard (FCS) files. ",
    "plannotate": "[CLI Tool] A tool for annotating plasmid sequences with common features. ",
    "vina": "[CLI Tool] An open-source program for molecular docking and virtual screening, known for its speed and accuracy improvements over AutoDock 4.",
    "autosite": "[CLI Tool] A binding site detection tool used to identify potential ligand binding pockets on protein structures for molecular docking.",
}
