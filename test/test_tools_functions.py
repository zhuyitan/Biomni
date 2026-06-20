import os

from biomni.agent import A1
from biomni.config import default_config

# Argo Gateway API (Argonne National Laboratory internal LLM service)
# OpenAI-compatible endpoint: https://apps.inside.anl.gov/argoapi/v1
# API key = your ANL domain username (not your full email address)
ARGO_BASE_URL = "https://apps.inside.anl.gov/argoapi/v1"
ARGO_USER = os.environ.get("ARGO_USER", "yitan.zhu")

# Route tools that read default_config (literature + database helpers) through
# Argo's OpenAI-compatible endpoint. biomni.llm.get_llm sees a non-"claude-"
# prefix on names like "claudesonnet47" and a base_url, so it picks the
# "Custom" branch — a ChatOpenAI client that POSTs to {base_url}/chat/completions.
# That requires the /v1 suffix; without it the URL is /argoapi/chat/completions
# and Argo returns 404. The A1 agent still uses gpt54 from its own ctor args.
default_config.llm = "claudesonnet46"  # valid Argo Claude IDs: claudesonnet46, claudeopus47, claudehaiku45 (no claudesonnet47)
default_config.api_key = ARGO_USER
default_config.base_url = ARGO_BASE_URL

# Argo model name for GPT-5.4 is "gpt54" (production; 1M token context, 128K output)
agent = A1(
    path="./data",
    llm="gpt54",
    source="Custom",
    base_url=ARGO_BASE_URL,
    api_key=ARGO_USER,
)

# Argo's gpt4o rejects the 'stop' parameter; clear it after LLM construction
agent.llm.stop = None

# Test TCGAbiolinks to retrive TCGA data.
agent.go("Please retrieve gene expression data of 5 lung adenocarcinoma (LUAD) samples from TCGA using TCGAbiolinks, and summarize the data in a table with columns: sample ID, gene symbol, expression value. Please provide the code you used to retrieve the data and generate the table.")

# # test query_pubmed. Successful.
# from biomni.tool.literature import query_pubmed

# queries = [
#     "lung cancer ionizing radiation ATM activation CHK2",
#     "NSCLC radiation ATM phosphorylation CHK2",
#     "lung cancer irradiated ATM Ser1981",
# ]
# for q in queries:
#     print(f"\n=== QUERY: {q} ===")
#     result = query_pubmed(q, max_papers=5)
#     print(result)


# # Test query_geo. Successful.
# from biomni.tool.database import query_geo

# print("Step 1: Searching GEO for lung cancer radiation-response transcriptomic datasets...")
# queries = [
#     "lung cancer ionizing radiation transcriptome CDC25A CHEK2 ATM",
#     "NSCLC irradiation gene expression",
#     "lung cancer radiation response GEO",
#     "A549 irradiation expression GEO"
# ]
# geo_results = {}
# for q in queries:
#     result = query_geo(prompt=q, max_results=5)
#     geo_results[q] = result
#     print(f"\nQuery: {q}")
#     print(result)



# # test query_scholar. The search result is just one paper and the abstract is very much condensed and doest not seem correct.
# from biomni.tool.literature import query_scholar

# queries = [
#     "ATM CHK2 CDC25A ionizing radiation lung cancer",
#     "CHK2 phosphorylates CDC25A degradation ionizing radiation",
#     "CDC25A degradation cell cycle arrest lung cancer",
# ]
# for q in queries:
#     print(f"\n=== SCHOLAR QUERY: {q} ===")
#     result = query_scholar(q)
#     print(result)



# # Test google search function. Failed, because the IP is blocked by Google. Will need to use proxy to test it.
# from googlesearch import search

# query = "Evidence ATM activates CHK2 after ionizing radiation in lung cancer cells publication"
# results = list(search(query, num_results=9, advanced=True))

# for i, r in enumerate(results, 1):
#     print(f"{i}. {r.title}\n   {r.url}\n   {r.description}\n")



# # test advanced_web_search_claude. Failed, because Argo has not enabled the search tool of claude, and when fallback to google search, the IP is blocked by Google. 
# Will need to use proxy to test it.
# from biomni.tool.literature import advanced_web_search_claude

# queries = [
#     "Evidence ATM activates CHK2 after ionizing radiation in lung cancer cells publication",
#     "Evidence CHK2 phosphorylates CDC25A leading to degradation publication",
#     "Evidence CDC25A degradation causes cell cycle arrest in lung cancer publication",
# ]
# for q in queries:
#     print(f"\n=== ADVANCED WEB SEARCH: {q} ===")
#     result = advanced_web_search_claude(q, max_searches=3)
#     print(result)



# # test search_google. Failed, because the IP is blocked by Google. Will need to use proxy to test it.
# from biomni.tool.literature import search_google

# queries = [
#     "ATM CHK2 ionizing radiation CDC25A paper",
#     "CHK2 CDC25A degradation paper",
#     "CDC25A degradation cell cycle arrest lung cancer paper",
# ]
# for q in queries:
#     print(f"\n=== GOOGLE SEARCH: {q} ===")
#     result = search_google(q, num_results=5)
#     print(result)