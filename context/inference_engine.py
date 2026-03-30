import json
import os
import uuid
from core.planner import Planner

PROMPT = """You are analyzing a sequence of XML UI Views captured every few seconds while a user was using an iOS app.
Your job is to deduce WHAT the user did to transition between each state, and write a '.spectra' JSONL execution script that could replay their routine.

Screens ({N} total):
{screens}

INSTRUCTIONS:
1. Examine the differences between Screen N and Screen N+1 to infer what button was tapped, or what text was typed.
2. For each inferred step, generate a valid Spectra JSONL "action" line.
3. Supported actions: tap (needs ref), type_text (needs ref and text), scroll.
4. IMPORTANT: Do NOT include your thinking process or json markdown blocks (`json`). Output EXACTLY two raw text sections separated by 3 dashes `---`.
   Section 1: A one-sentence summary of what the user achieved (e.g. "Sent a message to Mom").
   Section 2: The raw JSONL script lines, one per line. Do not wrap in markdown quotes. Start with `{"type": "header", "task": "<summary>"}`.
"""

def infer_spectra_flow(frames: list[dict]) -> tuple[str, str]:
    """Takes a list of frame dicts and returns (spectra_file_path, task_description)"""
    if len(frames) < 2:
        return None, ""
        
    screen_xml_parts = []
    for i, f in enumerate(frames):
        # Truncate tree to avoid exploding token window (first 2500 chars)
        short_tree = f['tree'][:2500] + "\n...[truncated]"
        screen_xml_parts.append(f"=== Screen {i+1} : {f['app']} ===\n{short_tree}\n")
        
    screens_text = "\n".join(screen_xml_parts)
    prompt = PROMPT.format(N=len(frames), screens=screens_text)
    
    planner = Planner()
    try:
        from google.genai import types
        config = types.GenerateContentConfig(max_output_tokens=1000, temperature=0.2)
        res = planner.client.models.generate_content(
            model=planner.model,
            contents=[types.Content(role='user', parts=[types.Part(text=prompt)])],
            config=config,
        )
        
        output = res.text.strip().split('---')
        if len(output) != 2:
            return None, "Inference format error"
            
        summary = output[0].strip()
        jsonl_script = output[1].strip()
        
        # Remove any stray markdown formatting
        if jsonl_script.startswith('```json'):
            jsonl_script = jsonl_script[7:]
        if jsonl_script.startswith('```'):
            jsonl_script = jsonl_script[3:]
        if jsonl_script.endswith('```'):
            jsonl_script = jsonl_script[:-3]
        jsonl_script = jsonl_script.strip()
        
        import time
        file_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        save_path = os.path.expanduser(f"~/.spectra/flows/{file_id}.spectra")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        with open(save_path, 'w') as f:
            f.write(jsonl_script + '\n')
            
        return save_path, summary
    except Exception as e:
        print(f"Inference Engine LLM Error: {e}")
        return None, ""
