import os
import glob

css_payload = """
        /* Mobile Optimization */
        @media (max-width: 600px) {
            .container, .main-container { padding: 1rem; width: 100%; max-width: 100%; box-sizing: border-box; margin: 0; border-radius: 0; border: none; min-height: 100vh; }
            .input-area, .button-group { flex-direction: column; gap: 8px; }
            .input-area input[type="text"], .input-area button, .button-group button { width: 100%; box-sizing: border-box; }
            .modal-content { width: 95%; padding: 1.5rem; margin: 0 auto; }
            header { flex-direction: column; gap: 10px; text-align: center; }
            header h1 { font-size: 1.3rem; text-align: center; }
            .nav-bar, .navbar { padding: 1rem; flex-wrap: wrap; gap: 10px; }
            .navbar > div { width: 100%; display: flex; justify-content: space-between; margin-top: 5px; }
            .result-card, .diary-card, .chat-box { width: 100%; box-sizing: border-box; padding: 15px; }
            .msg { max-width: 100%; padding: 1rem; font-size: 1rem; }
            .status-grid { flex-direction: column; gap: 5px; }
            .choice-btn { padding: 1rem; }
            .grid-container { grid-template-columns: 1fr; }
            button { word-break: keep-all; }
            img { max-width: 100%; height: auto; }
        }
"""

patched_files = []

for filepath in glob.glob("templates/**/*.html", recursive=True):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Don't patch if it already has "Max-width: 600px" generically
    # Wait, some might have it but poorly designed.
    # Let's just blindly inject before </style> or before closing <style> tag.
    
    # If the exact comment signature exists, don't double append
    if "/* Mobile Optimization */" in content and "@media (max-width: 600px)" in content:
        continue
        
    if "</style>" in content:
        # replace the last occurrence of </style>
        # just in case
        parts = content.rsplit("</style>", 1)
        new_content = parts[0] + css_payload + "</style>" + parts[1]
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        patched_files.append(filepath)

print(f"Patched {len(patched_files)} files: {patched_files}")
