# Qudron approval-key operations

Qudron uses Ed25519 so runtime workers can verify one-time approvals without
having the ability to mint them.

## Trust boundary

- The owner-only issuer host holds the private key.
- Qudron runtime workers receive only the public key.
- Never put the private key in the repository, shared `.env`, OpenDots, FreeLLM,
  agent context, container image, or worker volume.
- The issuer CLI records the operating-system login name in the signed
  `approved_by` claim. Access to the private key and issuer host is the
  authorization boundary; this is not a substitute for enterprise identity
  management or a tamper-resistant audit service.

## Provision keys

On a trusted owner-only machine, from the runtime source directory:

```bash
python scripts/generate_approval_keys.py \
  --private-key /secure/qudron-owner/approval-ed25519-private.pem \
  --public-key /secure/qudron-runtime/approval-ed25519-public.pem
```

Add `--encrypt` to protect the private PEM with an interactive passphrase.
The generator refuses to overwrite existing key files and creates the private
file with mode 0600. Back up the private key securely; losing it requires
controlled key rotation and invalidates the ability to issue approvals.

Mount only the public PEM into the Qudron runtime and set:

```dotenv
QUDRON_APPROVAL_PUBLIC_KEY_FILE=/run/secrets/approval-ed25519-public.pem
```

On the owner-only issuer host, set the private-key path separately:

```bash
export QUDRON_APPROVAL_PRIVATE_KEY_FILE=/secure/qudron-owner/approval-ed25519-private.pem
# Only when the PEM was encrypted:
export QUDRON_APPROVAL_PRIVATE_KEY_PASSPHRASE='read-from-owner-secret-store'
```

Do not add the private-key variables to the runtime's shared `.env`.

## Issue an approval

The owner explicitly runs the issuer after reviewing the exact action and target:

```bash
python scripts/issue_approval.py \
  --action workflow.node.approve \
  --resource-id 'workflow-id/node-id' \
  --ttl-seconds 300
```

The command prints a short-lived, scope-bound, one-time token. Deliver it only
to the intended approval-gated operation. Do not paste it into logs, tickets,
chat history, or agent prompts. The runtime consumes the nonce atomically, so
replay is rejected.

The `action` and `resource-id` values must match the exact verifier call site.
This CLI does not grant an action by itself, and it does not enable an
integration that has not been separately configured and tested.

## Operational acceptance

Before enabling approval-gated production actions, verify:

1. The owner issuer can load the private key and issue a token.
2. A runtime configured with only the public key accepts a valid token.
3. A runtime with no public key fails closed.
4. A worker cannot load the private key or issue a token.
5. Expired, wrong-action, wrong-resource, tampered and replayed tokens fail.
6. Nonce consumption is atomic under concurrent requests.
7. The private key is absent from runtime/FreeLLM containers and image layers.
8. Key rotation, backup, revocation and owner identity procedures are documented.

This repository supplies the key-generation and token-issuance utilities plus
contract tests. It does not provision the owner's secret store or runtime
secret mount; those remain deployment-owner actions.
