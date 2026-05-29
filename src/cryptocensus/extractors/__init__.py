"""Independent extractors that read a flattened image root filesystem.

Each extractor is pure with respect to the filesystem: given a root directory it
returns typed records and never mutates global state, so extractors compose and can
be toggled individually for ablation studies.
"""
