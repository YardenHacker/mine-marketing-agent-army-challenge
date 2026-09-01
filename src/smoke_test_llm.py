"""
Task C, Step C0: confirm ANTHROPIC_API_KEY works before any real spend.
One tiny call, max_tokens capped hard, cost printed but never the key itself.
"""
import os
from dotenv import load_dotenv
import anthropic

load_dotenv()

key = os.environ.get("ANTHROPIC_API_KEY")
if not key:
    raise SystemExit("ANTHROPIC_API_KEY not found in environment or .env")

client = anthropic.Anthropic(api_key=key)

resp = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=20,
    messages=[{"role": "user", "content": "Reply with exactly: OK"}],
)

text = resp.content[0].text if resp.content else "(empty)"
usage = resp.usage
in_tok, out_tok = usage.input_tokens, usage.output_tokens
# Haiku 4.5: $1/$5 per million input/output tokens
cost = (in_tok / 1e6) * 1 + (out_tok / 1e6) * 5

print(f"Model responded: {text!r}")
print(f"Tokens: {in_tok} in, {out_tok} out")
print(f"Cost: ${cost:.6f}")
print("Connectivity confirmed.")
