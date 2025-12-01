import json
import sys
import uuid
import random
import string

def random_suffix(length=4):
    """Generate a random alphanumeric suffix."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def generate_transactions(n, key_ids):
    transactions = []
    for i in range(1, n + 1):
        tx_id = f"tx{i}_{random_suffix()}"
        key_id = random.choice(key_ids)  # pick a random key_id from the set
        tx = {
            "id": tx_id,
            "content": json.dumps({
                "command": "SIGN",
                "key_id": key_id,
                "data": f"data-{uuid.uuid4().hex[:8]}"
            })
        }
        transactions.append(tx)
    return transactions


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <num_transactions> <key_id1> [<key_id2> ...]")
        sys.exit(1)

    n = int(sys.argv[1])
    key_ids = sys.argv[2:]  # list of key_ids from CLI

    result = generate_transactions(n, key_ids)
    print(json.dumps(result, indent=2))

