from typing import final

LOW_RANKS: final = (
    "Customer",
    "Trainee",
    "Junior Operator",
    "Senior Operator",
    "Head Operator",
)
MID_RANKS: final = (
    "Shift Leader",
    "Supervisor",
    "Assistant Manager",
    "General Manager",
)
MGMT_RANKS: final = (
    "Assistant Director",
    "Junior Director",
    "Senior Director",
    "Head Director",
)
CORP_RANKS: final = (
    "Corporate Intern",
    "Junior Corporate",
    "Senior Corporate",
    "Head Corporate",
)
LS_RANKS: final = (
    "Chief Human Resources Officer",
    "Chief Public Relations Officer",
    "Chief Operating Officer",
    "Chief Administrative Officer",
    "Developer",
    "Vice Chairman",
    "Chairman",
)

ET_RANKS: final = LOW_RANKS 
"""All roles in the "Entry-Level" category as one tuple, in order of hierarchy. This is a flattened, immutable tuple containing all entry-level ranks."""
ST_RANKS: final = MID_RANKS 
"""All roles in the "Senior-Level" category as one tuple, in order of hierarchy. This is a flattened, immutable tuple containing all senior-level ranks."""

HIGH_RANKS: final = MGMT_RANKS + CORP_RANKS + LS_RANKS
ALL_RANKS: final = ET_RANKS + MID_RANKS + HIGH_RANKS
"""All roles as one tuple, in order of hierarchy. This is a flattened, immutable tuple containing all rank categories."""

# Flatten into fixed tuple
ALL_M_RANKS_LIST: final = (
    ET_RANKS,
    ST_RANKS,
    MGMT_RANKS,
    CORP_RANKS,
    LS_RANKS,
)
"""ALL_M_RANKS_LIST is a nested, immutable tuple containing all rank categories as sub-tuples."""