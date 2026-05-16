import pandas as pd

parquet_path = "../biomni_eval1/biomni_eval1_dataset.parquet"
df = pd.read_parquet(parquet_path)

print("=== Shape ===")
print(f"Rows: {df.shape[0]}, Columns: {df.shape[1]}")

print("\n=== Columns and dtypes ===")
print(df.dtypes.to_string())

print("\n=== First 3 rows ===")
pd.set_option("display.max_columns", None)
pd.set_option("display.max_colwidth", 80)
print(df.head(3).to_string())

print("\n=== Null counts ===")
print(df.isnull().sum().to_string())

print("\n=== Unique values per column ===")
for col in df.columns:
    n = df[col].nunique()
    print(f"  {col}: {n} unique values")
