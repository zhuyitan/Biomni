#!/bin/bash
# Added by biomni setup
# Remove any old paths first to avoid duplicates
PATH=$(echo $PATH | tr ':' '\n' | grep -v "biomni_tools/bin" | tr '\n' ':' | sed 's/:$//')
export PATH="/nfs/ml_lab/projects/Pilot1_PreclinicalHPC/yitan.zhu/Projects/IMPROVE/luma/claude_code/biomni_env/biomni_tools/bin:$PATH"
