from biomni.agent import A1

# Initialize the agent with data path, Data lake will be automatically downloaded on first run (~11GB)
agent = A1(path="./data", llm="gpt-4o", source="OpenAI")

# Execute biomedical tasks using natural language
# agent.go("Plan a CRISPR screen to identify genes that regulate T cell exhaustion, generate 32 genes that maximize the perturbation effect.")
# agent.go("Perform scRNA-seq annotation at [PATH] and generate meaningful hypothesis")
agent.go("Predict ADMET properties for this compound: CC(C)CC1=CC=C(C=C1)C(C)C(=O)O")


# from biomni.agent import A1

# agent = A1(path='./data', llm='gpt-4o', source='OpenAI')
# agent.launch_gradio_demo()

# # In terminal, construact the tunnel and open the provided URL in your browser to access the Gradio interface.
# # ssh -L 7860:localhost:7860 yitan.zhu@lambda0.cels.anl.gov

# http://localhost:7860/





# from biomni.config import default_config
# from biomni.agent import A1

# default_config.llm = "gpt-4o"      # or another OpenAI model you have access to
# default_config.source = "OpenAI"

# agent = A1(path="./data")



