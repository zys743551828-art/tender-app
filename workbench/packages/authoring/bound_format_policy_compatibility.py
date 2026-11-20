"""Exact pre-V3 equivalents; never relabel unreviewed source bytes."""

V2_EQUIVALENTS: dict[str, tuple[str, str]] = {
    "packages/authoring/package_admission.py": (
        "02f7906fb29126f12b6cd3bd56b1a2c7daa316b0e5c737acf76b03c2a8b20fdd",
        "c63c3f63328efc81066029e36680dec1c360aa2a0f7bf73757962ca2874c1a2b",
    ),
    "packages/authoring/package_generation.py": (
        "215c5a2f094d8a429ba3fc4555bb8348edba95a76e210d7852ec956976f7de69",
        "c28055907a113adf3ebf4cc24745730e96a875b0ba4dac4563d1258494856860",
    ),
    "packages/authoring/package_input_observation.py": (
        "5415ed991a48e4f868a1d90aec2028b48efb18f0d36ff97fde7834d17fee3bf5",
        "702644cc36d5be7b3d841af43e49af7f293d25072f5c60c26bd8f5c4563abacc",
    ),
    "packages/authoring/package_job_authority.py": (
        "0db40a19ca4c3497e540bb56aedef1d9defe42f8d9ef897282b83b29b43018dc",
        "ca2337a1fcc819c9f78ecb7943a58af41914679459dedd237f4fab694e95606f",
    ),
    "packages/authoring/plan_policy_compatibility.py": (
        "c1c9dd072571eceb7da06a9f519c8163ad17003ea8b8b30b548aff89afeec3a2",
        "766a6d18a0417284dd95d41d989cde507987f1efd9bc59d1ad651da7fce1aaa4",
    ),
}
