"""CryptoCensus: a reproducible, distributed census of the cryptographic posture
and post-quantum readiness of public container images.

The package is organized into:
  - extractors/  : independent collectors that read a flattened image root filesystem
  - classify     : algorithm -> {quantum-vulnerable, post-quantum, symmetric, hash} mapping
  - batchgcd     : shared-prime weak-key detection over harvested RSA moduli
  - cbom         : CycloneDX 1.7 Cryptography Bill of Materials serialization
  - queue        : Redis-backed reliable, multi-machine task queue
  - worker       : claim -> pull -> extract -> classify -> emit result
  - coordinator  : seed the queue from a sample
  - collector    : drain results into a local dataset
  - analyze      : aggregate posture, PQC readiness, key reuse and tool divergence
"""

__version__ = "0.1.0"
