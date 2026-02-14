"""Seed script: populate the database with demo data for the Johnson family scenario."""

import asyncio
import json
from datetime import datetime, timezone

from src.crypto import derive_vault_key, encrypt, encrypt_text, generate_key, generate_ed25519_keypair, hash_pin, public_key_to_did
from src.database import drop_db, init_db, async_session
from src.embeddings import reset_collection, upsert_capsule_embedding
from src.models import (
    Agent,
    CapsuleNetworkAccess,
    Connection,
    KnowledgeCapsule,
    Network,
    NetworkMembership,
    SharingDelegate,
    User,
)

# Shared password for demo (simplified for hackathon — 16+ chars required)
DEMO_PASSWORD = "TrustMesh-demo-2026"

USERS = [
    {
        "username": "peter",
        "display_name": "Peter Johnson",
        "bio": "Licensed electrician, dad of two. Guitar player, loves classic rock. Active in the Riverside neighborhood.",
        "agent_personality": "Helpful and practical. Expert in electrical work and home safety. Protective dad. Enjoys talking about music and guitars.",
        "profile_data": {
            "occupation": {"title": "Licensed Electrician", "industry": "Electrical Services", "years": 20},
            "skills": [
                {"name": "Residential Wiring", "category": "certified"},
                {"name": "Panel Upgrades", "category": "certified"},
                {"name": "Guitar", "category": "hobby"},
            ],
            "interests": [
                {"name": "Classic Rock", "category": "music"},
                {"name": "Home Improvement", "category": "hobby"},
            ],
            "family_status": "married",
            "age_range": "40s",
            "location_hints": ["Riverside", "Bay Area"],
        },
    },
    {
        "username": "molly",
        "display_name": "Molly Johnson",
        "bio": "Project manager at TechCorp. Mom, caretaker for Grandma Rose. Salsa dancing enthusiast.",
        "agent_personality": "Organized and caring. Manages work projects and family care duties. Very detail-oriented about grandma's medical needs.",
        "profile_data": {
            "occupation": {"title": "Sr. Project Manager", "industry": "Technology", "company": "TechCorp"},
            "skills": [
                {"name": "Project Management", "category": "professional"},
                {"name": "Agile/Scrum", "category": "professional"},
                {"name": "Salsa Dancing", "category": "hobby"},
            ],
            "interests": [
                {"name": "Salsa Dancing", "category": "hobby"},
                {"name": "Elder Care", "category": "personal"},
            ],
            "family_status": "married",
            "age_range": "40s",
            "location_hints": ["Riverside", "Bay Area"],
        },
    },
    {
        "username": "jane",
        "display_name": "Jane Johnson",
        "bio": "10th grader at Lincoln High. Varsity soccer, watercolor painting, and debate club.",
        "agent_personality": "Friendly and energetic. Shares school and activity info openly with family.",
        "profile_data": {
            "occupation": {"title": "Student", "industry": "Education", "school": "Lincoln High"},
            "skills": [
                {"name": "Soccer (Midfield)", "category": "athletic"},
                {"name": "Watercolor Painting", "category": "creative"},
                {"name": "Debate", "category": "academic"},
            ],
            "interests": [
                {"name": "Art", "category": "creative"},
                {"name": "Soccer", "category": "sports"},
            ],
            "family_status": "child",
            "age_range": "teen",
            "location_hints": ["Riverside"],
        },
    },
    {
        "username": "bill",
        "display_name": "Bill Johnson",
        "bio": "8th grader at Roosevelt Middle. Learning Python, gaming, and soccer.",
        "agent_personality": "Casual and helpful. Shares school and activity info with family.",
        "profile_data": {
            "occupation": {"title": "Student", "industry": "Education", "school": "Roosevelt Middle"},
            "skills": [
                {"name": "Python (learning)", "category": "technical"},
                {"name": "Soccer", "category": "athletic"},
                {"name": "Gaming", "category": "hobby"},
            ],
            "interests": [
                {"name": "Coding", "category": "technical"},
                {"name": "Gaming", "category": "hobby"},
            ],
            "family_status": "child",
            "age_range": "teen",
            "location_hints": ["Riverside"],
        },
    },
    {
        "username": "kyle",
        "display_name": "Kyle Rivera",
        "bio": "Software engineer at TechCorp. Open source contributor. Plays basketball on weekends.",
        "agent_personality": "Professional and technical. Shares work-related info with teammates.",
        "profile_data": {
            "occupation": {"title": "Sr. Software Engineer", "industry": "Technology", "company": "TechCorp"},
            "skills": [
                {"name": "Backend Systems", "category": "professional"},
                {"name": "API Design", "category": "professional"},
                {"name": "TypeScript", "category": "professional"},
                {"name": "Open Source", "category": "professional"},
            ],
            "interests": [
                {"name": "Basketball", "category": "sports"},
                {"name": "Open Source", "category": "technical"},
            ],
            "family_status": "single",
            "age_range": "30s",
            "location_hints": ["Bay Area"],
        },
    },
    {
        "username": "grandmarose",
        "display_name": "Grandma Rose",
        "bio": "Retired schoolteacher. Loves gardening, bridge club, and spoiling grandkids. Living in Riverside senior community.",
        "agent_personality": "Warm and wise. Shares stories and advice freely. Protective of health info but open about social activities.",
        "profile_data": {
            "occupation": {"title": "Retired Teacher", "industry": "Education"},
            "skills": [
                {"name": "Teaching", "category": "professional"},
                {"name": "Gardening", "category": "hobby"},
                {"name": "Bridge", "category": "hobby"},
            ],
            "interests": [
                {"name": "Gardening", "category": "hobby"},
                {"name": "Bridge Club", "category": "social"},
                {"name": "Grandkids", "category": "family"},
            ],
            "family_status": "widowed",
            "age_range": "70s",
            "location_hints": ["Riverside Senior Community"],
        },
    },
    {
        "username": "linda",
        "display_name": "Linda Chen",
        "bio": "Architect at Chen Design. Neighbor to the Johnsons at 45 Oak St. Community garden organizer.",
        "agent_personality": "Friendly and community-minded. Shares neighborhood info openly. Helpful with local knowledge.",
        "profile_data": {
            "occupation": {"title": "Architect", "industry": "Architecture", "company": "Chen Design"},
            "skills": [
                {"name": "Sustainable Design", "category": "professional"},
                {"name": "Residential Architecture", "category": "professional"},
                {"name": "Community Organizing", "category": "volunteer"},
            ],
            "interests": [
                {"name": "Community Garden", "category": "volunteer"},
                {"name": "Sustainable Design", "category": "professional"},
            ],
            "family_status": "single",
            "age_range": "40s",
            "location_hints": ["45 Oak St", "Riverside"],
        },
    },
    {
        "username": "amy",
        "display_name": "Amy Torres",
        "bio": "10th grader at Lincoln High. Co-captain of varsity soccer with Jane. Wants to study marine biology.",
        "agent_personality": "Outgoing and sporty. Shares team and school info openly.",
        "profile_data": {
            "occupation": {"title": "Student", "industry": "Education", "school": "Lincoln High"},
            "skills": [
                {"name": "Soccer (Co-Captain)", "category": "athletic"},
                {"name": "Marine Biology (aspiring)", "category": "academic"},
            ],
            "interests": [
                {"name": "Marine Biology", "category": "academic"},
                {"name": "Soccer", "category": "sports"},
                {"name": "Aquarium Volunteering", "category": "volunteer"},
            ],
            "family_status": "child",
            "age_range": "teen",
            "location_hints": ["Bay Area"],
        },
    },
    {
        "username": "marcus",
        "display_name": "Marcus Williams",
        "bio": "8th grader at Roosevelt Middle. Coding club president, building a Minecraft mod. Science fair winner.",
        "agent_personality": "Enthusiastic about tech. Shares coding projects and school activities.",
        "profile_data": {
            "occupation": {"title": "Student", "industry": "Education", "school": "Roosevelt Middle"},
            "skills": [
                {"name": "Java (Minecraft Modding)", "category": "technical"},
                {"name": "Python", "category": "technical"},
                {"name": "AI/ML (learning)", "category": "technical"},
            ],
            "interests": [
                {"name": "Coding", "category": "technical"},
                {"name": "Minecraft", "category": "gaming"},
                {"name": "Science Fair", "category": "academic"},
            ],
            "family_status": "child",
            "age_range": "teen",
            "location_hints": ["Bay Area"],
        },
    },
    {
        "username": "dorothy",
        "display_name": "Dorothy Park",
        "bio": "Retired librarian. Rose's best friend from bridge club. Volunteers at Riverside community center.",
        "agent_personality": "Kind and well-read. Shares community events and book recommendations freely.",
        "profile_data": {
            "occupation": {"title": "Retired Librarian", "industry": "Education"},
            "skills": [
                {"name": "Library Science", "category": "professional"},
                {"name": "Book Club Facilitation", "category": "volunteer"},
                {"name": "Community Events", "category": "volunteer"},
            ],
            "interests": [
                {"name": "Reading", "category": "hobby"},
                {"name": "Bridge Club", "category": "social"},
                {"name": "Volunteering", "category": "community"},
            ],
            "family_status": "widowed",
            "age_range": "70s",
            "location_hints": ["Riverside"],
        },
    },
    # ── Healthcare Practitioners ──
    {
        "username": "dr_lee",
        "display_name": "Dr. Sarah Lee",
        "bio": "Emergency medicine physician at Riverside General Hospital. Board certified, 12 years experience. Specializes in cardiac emergencies.",
        "agent_personality": "Calm under pressure, clinically precise. Requests only the data needed for treatment. Follows HIPAA protocols strictly.",
        "profile_data": {
            "occupation": {"title": "ER Physician", "industry": "Healthcare", "institution": "Riverside General Hospital"},
            "skills": [
                {"name": "Emergency Medicine", "category": "medical"},
                {"name": "Cardiac Emergencies", "category": "medical"},
                {"name": "Trauma", "category": "medical"},
            ],
            "interests": [],
            "family_status": "unknown",
            "age_range": "40s",
            "location_hints": ["Riverside"],
        },
    },
    {
        "username": "nurse_davis",
        "display_name": "Nurse Rachel Davis",
        "bio": "ER nurse at Riverside General Hospital. 8 years experience. Triage specialist. BLS/ACLS certified.",
        "agent_personality": "Efficient and compassionate. Focuses on immediate patient needs — allergies, vitals, medications.",
        "profile_data": {
            "occupation": {"title": "ER Nurse", "industry": "Healthcare", "institution": "Riverside General Hospital"},
            "skills": [
                {"name": "Triage", "category": "medical"},
                {"name": "BLS/ACLS/PALS", "category": "certified"},
                {"name": "Patient Assessment", "category": "medical"},
            ],
            "interests": [],
            "family_status": "unknown",
            "age_range": "30s",
            "location_hints": ["Riverside"],
        },
    },
    {
        "username": "emt_johnson",
        "display_name": "EMT Mike Johnson",
        "bio": "Paramedic with Riverside City Ambulance. 6 years experience. Advanced life support certified.",
        "agent_personality": "Quick and focused. Needs critical info fast — allergies, DNR status, emergency contacts.",
        "profile_data": {
            "occupation": {"title": "Paramedic", "industry": "Healthcare", "institution": "Riverside City Ambulance"},
            "skills": [
                {"name": "Advanced Life Support", "category": "certified"},
                {"name": "Cardiac Response", "category": "medical"},
                {"name": "Field Assessment", "category": "medical"},
            ],
            "interests": [],
            "family_status": "unknown",
            "age_range": "30s",
            "location_hints": ["Riverside"],
        },
    },
]

SERVICE_PROVIDERS = [
    {
        "username": "sparkleclean",
        "display_name": "SparkleClean Residential",
        "bio": "Professional residential cleaning in the Bay Area. Standard, deep, and move-out cleans. Licensed and insured. Serving families since 2015.",
        "user_type": "organization",
        "agent_personality": "Professional, detail-oriented. Provides clear quotes with breakdowns. Asks about home size, pets, and special requests.",
        "profile_data": {
            "occupation": {"title": "Cleaning Service", "industry": "Home Services"},
            "skills": [
                {"name": "Residential Cleaning", "category": "professional"},
                {"name": "Deep Cleaning", "category": "professional"},
                {"name": "Move-out Cleaning", "category": "professional"},
            ],
            "interests": [],
            "family_status": "unknown",
            "age_range": None,
            "location_hints": ["Bay Area", "San Francisco", "Oakland"],
        },
        "capsules": [
            {
                "type": "skill",
                "title": "Pricing & Services",
                "content": "Standard clean: $150-250 (up to 2000sqft), $0.10/sqft above. Deep clean: 2x standard. Move-out: 2.5x standard. Add-ons: inside fridge $40, inside oven $35, windows $8/each. We bring all supplies. 2-person team, 2-3 hours standard.",
                "visibility": "open",
                "category": "general",
            },
            {
                "type": "schedule",
                "title": "Availability",
                "content": "Available M-Sat, 8am-5pm. Book 3+ days ahead for standard, 1 week for deep clean. Same-day available for $50 surcharge. Holiday rates apply Dec 20-Jan 5.",
                "visibility": "open",
                "category": "general",
            },
            {
                "type": "preference",
                "title": "Service Area",
                "content": "Bay Area: San Francisco, Oakland, Berkeley, San Mateo, Palo Alto, Mountain View. Travel fee $25 for South Bay beyond Sunnyvale.",
                "visibility": "open",
                "category": "general",
            },
        ],
    },
    {
        "username": "acetutor",
        "display_name": "AceTutor SAT Prep",
        "bio": "SAT/ACT prep specialist. 15+ years experience, average 200-point improvement. Small groups and 1-on-1. Serving Bay Area students.",
        "user_type": "organization",
        "agent_personality": "Encouraging, knowledgeable about test strategy. Asks about target score, weak areas, and timeline.",
        "profile_data": {
            "occupation": {"title": "SAT Tutor", "industry": "Education"},
            "skills": [
                {"name": "SAT Prep", "category": "professional"},
                {"name": "ACT Prep", "category": "professional"},
                {"name": "Reading Comprehension", "category": "professional"},
                {"name": "Math Tutoring", "category": "professional"},
            ],
            "interests": [],
            "family_status": "unknown",
            "age_range": None,
            "location_hints": ["Bay Area", "Roosevelt Middle"],
        },
        "capsules": [
            {
                "type": "skill",
                "title": "SAT Prep Programs",
                "content": "1-on-1 tutoring: $75/hr. Small group (3-5 students): $45/hr per student. Intensive 8-week program: $1200 (includes materials). Diagnostic test included free. Focus areas: Reading comprehension, Math problem-solving, Writing. Average improvement: 200 points over 10 sessions.",
                "visibility": "open",
                "category": "general",
            },
            {
                "type": "schedule",
                "title": "Availability & Location",
                "content": "Evenings M-Th 4-8pm, Sat 9am-3pm. In-person at our center (456 Oak St, near Roosevelt Middle) or online via Zoom. 24hr cancellation policy.",
                "visibility": "open",
                "category": "general",
            },
            {
                "type": "preference",
                "title": "Tutor Profiles",
                "content": "Sarah (lead tutor): Stanford grad, 15 years. Specializes in reading comp and essay. Marcus: Berkeley grad, 8 years. Math specialist, 800 math SAT. Lisa: Online-only, flexible hours, great with shy students.",
                "visibility": "open",
                "category": "general",
            },
        ],
    },
    {
        "username": "handypro",
        "display_name": "HandyPro Home Services",
        "bio": "Licensed general contractor. Electrical, plumbing, carpentry, painting. Free estimates. Same-day emergency service available.",
        "user_type": "organization",
        "agent_personality": "Practical, no-nonsense. Gives clear timelines and pricing. Asks about urgency and scope.",
        "profile_data": {
            "occupation": {"title": "General Contractor", "industry": "Home Services"},
            "skills": [
                {"name": "Electrical", "category": "certified"},
                {"name": "Plumbing", "category": "certified"},
                {"name": "Carpentry", "category": "professional"},
                {"name": "Painting", "category": "professional"},
            ],
            "interests": [],
            "family_status": "unknown",
            "age_range": None,
            "location_hints": ["Bay Area"],
        },
        "capsules": [
            {
                "type": "skill",
                "title": "Services & Rates",
                "content": "Hourly rate: $85/hr (2hr minimum). Electrical: outlets, panels, lighting. Plumbing: leaks, fixtures, water heaters. Carpentry: shelving, decks, repairs. Painting: interior/exterior. Free estimates for jobs over $500. Emergency surcharge: $50.",
                "visibility": "open",
                "category": "general",
            },
            {
                "type": "schedule",
                "title": "Availability",
                "content": "M-F 7am-6pm, Sat 8am-2pm. Emergency service 24/7. Book 2+ days ahead for non-emergency. Currently 1-week backlog for large projects.",
                "visibility": "open",
                "category": "general",
            },
        ],
    },
    {
        "username": "riverside_hospital",
        "display_name": "Riverside General Hospital",
        "bio": "Full-service community hospital. Emergency department, ICU, surgery, and specialist clinics. Serving the Riverside community since 1952.",
        "user_type": "organization",
        "agent_personality": "Professional, urgent when needed. Handles emergency data requests with proper authorization. Follows HIPAA protocols.",
        "profile_data": {
            "occupation": {"title": "Hospital", "industry": "Healthcare"},
            "skills": [
                {"name": "Emergency Medicine", "category": "medical"},
                {"name": "Surgery", "category": "medical"},
                {"name": "Internal Medicine", "category": "medical"},
                {"name": "Pediatrics", "category": "medical"},
            ],
            "interests": [],
            "family_status": "unknown",
            "age_range": None,
            "location_hints": ["Riverside", "Bay Area"],
        },
        "capsules": [
            {
                "type": "skill",
                "title": "Emergency Department",
                "content": "24/7 emergency department. Level II trauma center. Average ER wait: 22 minutes. Accepts all major insurance and Medicare/Medicaid.",
                "visibility": "open",
                "category": "general",
            },
            {
                "type": "procedure",
                "title": "Emergency Data Access Protocol",
                "content": "For emergency medical situations, authorized practitioners can request scoped access to patient data via UCAN tokens. Access is time-bounded, role-scoped, and fully audited. Patients are notified of all access.",
                "visibility": "open",
                "category": "general",
            },
        ],
    },
    {
        "username": "riverside_ambulance",
        "display_name": "Riverside City Ambulance",
        "bio": "City ambulance service covering the Riverside district. 24/7 emergency response. Average response time: 7 minutes.",
        "user_type": "organization",
        "agent_personality": "Rapid, protocol-driven. Requests only critical patient data for field treatment. Follows EMS protocols.",
        "profile_data": {
            "occupation": {"title": "Ambulance Service", "industry": "Healthcare"},
            "skills": [
                {"name": "Emergency Response", "category": "medical"},
                {"name": "Advanced Life Support", "category": "medical"},
                {"name": "Patient Transport", "category": "medical"},
            ],
            "interests": [],
            "family_status": "unknown",
            "age_range": None,
            "location_hints": ["Riverside", "Bay Area"],
        },
        "capsules": [
            {
                "type": "skill",
                "title": "Emergency Response",
                "content": "24/7 emergency ambulance service. Average response time: 7 minutes. ALS-equipped units. Dispatch via 911 or direct at (555) 911-2000.",
                "visibility": "open",
                "category": "general",
            },
            {
                "type": "procedure",
                "title": "Field Data Access Protocol",
                "content": "Paramedics can request scoped access to patient data via UCAN tokens issued by dispatch. Access limited to: allergies, blood type, DNR status, emergency contacts. All access is logged and auditable.",
                "visibility": "open",
                "category": "general",
            },
        ],
    },
]

CONNECTIONS = [
    # Johnson family (personal)
    ("peter", "molly", "personal"),
    ("peter", "jane", "personal"),
    ("peter", "bill", "personal"),
    ("molly", "jane", "personal"),
    ("molly", "bill", "personal"),
    # Grandma Rose <-> family (personal)
    ("molly", "grandmarose", "personal"),
    ("peter", "grandmarose", "personal"),
    ("jane", "grandmarose", "personal"),
    ("bill", "grandmarose", "personal"),
    # Work
    ("molly", "kyle", "work"),
    # Siblings (personal)
    ("jane", "bill", "personal"),
    # Neighborhood (personal)
    ("peter", "linda", "personal"),
    ("molly", "linda", "personal"),
    # Kids' friends (personal)
    ("jane", "amy", "personal"),
    ("bill", "marcus", "personal"),
    # Grandma's circle (personal)
    ("grandmarose", "dorothy", "personal"),
    ("linda", "dorothy", "personal"),
    # Healthcare team (work)
    ("dr_lee", "nurse_davis", "work"),
    ("dr_lee", "emt_johnson", "work"),
    ("nurse_davis", "emt_johnson", "work"),
    # Healthcare practitioners ↔ institutions (work)
    ("dr_lee", "riverside_hospital", "work"),
    ("nurse_davis", "riverside_hospital", "work"),
    ("emt_johnson", "riverside_ambulance", "work"),
    ("emt_johnson", "riverside_hospital", "work"),
]

NETWORKS = [
    {
        "name": "The Johnsons",
        "type": "family",
        "description": "Johnson family knowledge sharing — health, schedules, and home info.",
        "owner": "peter",
        "members": ["peter", "molly", "jane", "bill"],
        "is_public": False,
        "join_policy": "invite_only",
        "context": "personal",
    },
    {
        "name": "TechCorp PM Team",
        "type": "team",
        "description": "TechCorp project management team — deadlines, reports, and API migration.",
        "owner": "molly",
        "members": ["molly", "kyle"],
        "is_public": True,
        "join_policy": "request_to_join",
        "context": "work",
    },
    {
        "name": "Rose's Care Circle",
        "type": "family",
        "description": "Coordinating Grandma Rose's care — medications, appointments, and daily routines.",
        "owner": "molly",
        "members": ["molly", "peter", "grandmarose", "dorothy"],
        "is_public": False,
        "join_policy": "invite_only",
        "context": "personal",
    },
    {
        "name": "Lincoln High Soccer",
        "type": "friends",
        "description": "Lincoln High varsity soccer team — practice schedules, game info, and team news.",
        "owner": "jane",
        "members": ["jane", "amy"],
        "is_public": True,
        "join_policy": "request_to_join",
        "context": "personal",
    },
    {
        "name": "Roosevelt Coding Club",
        "type": "friends",
        "description": "Roosevelt Middle coding club — Python projects, Minecraft mods, and science fair prep.",
        "owner": "marcus",
        "members": ["marcus", "bill"],
        "is_public": True,
        "join_policy": "open",
        "context": "personal",
    },
    {
        "name": "Riverside Neighbors",
        "type": "friends",
        "description": "Riverside neighborhood community — block parties, safety alerts, local recommendations.",
        "owner": "linda",
        "members": ["linda", "peter", "molly"],
        "is_public": True,
        "join_policy": "request_to_join",
        "context": "personal",
    },
    {
        "name": "Bay Area Music Lovers",
        "type": "custom",
        "description": "Local music community — jam sessions, concert tips, and instrument swap. All genres welcome!",
        "owner": "peter",
        "members": ["peter"],
        "is_public": True,
        "join_policy": "open",
        "context": "personal",
    },
    {
        "name": "Riverside Bridge Club",
        "type": "friends",
        "description": "Weekly bridge games at the community center. Thursdays 2-5pm. All skill levels.",
        "owner": "grandmarose",
        "members": ["grandmarose", "dorothy"],
        "is_public": True,
        "join_policy": "open",
        "context": "personal",
    },
    {
        "name": "Riverside ER Team",
        "type": "team",
        "description": "Riverside General Hospital emergency department staff — doctors, nurses, paramedics. UCAN-authorized emergency access.",
        "owner": "dr_lee",
        "members": ["dr_lee", "nurse_davis", "emt_johnson"],
        "is_public": False,
        "join_policy": "invite_only",
        "context": "work",
    },
    {
        "name": "Bay Area Salsa Social",
        "type": "custom",
        "description": "Salsa dancing community — classes, socials, and performances around the Bay Area.",
        "owner": "molly",
        "members": ["molly"],
        "is_public": True,
        "join_policy": "open",
        "context": "personal",
    },
]

# Category defaults for auto-suggested governance on creation
CATEGORY_DEFAULTS = {
    "health":   {"visibility": "internal", "emergency_accessible": True,  "can_reshare": False},
    "personal": {"visibility": "private",  "emergency_accessible": False, "can_reshare": False},
    "work":     {"visibility": "internal", "emergency_accessible": False, "can_reshare": False},
    "family":   {"visibility": "internal", "emergency_accessible": False, "can_reshare": False},
    "home":     {"visibility": "internal", "emergency_accessible": False, "can_reshare": False},
    "general":  {"visibility": "open",     "emergency_accessible": False, "can_reshare": True},
}

CAPSULES = [
    # ── PETER ──────────────────────────────────
    {
        "owner": "peter",
        "type": "skill",
        "title": "House Electrical Panel Layout",
        "content": (
            "Our house has 200A service, main panel is in the garage on the east wall. "
            "Breaker layout: 1-2 Kitchen (GFCI on counter outlets), 3-4 Living/Dining, "
            "5-6 Master bedroom + bathroom, 7-8 Jane's room + Bill's room, "
            "9-10 Garage + outdoor, 11-12 HVAC, 13-14 Water heater + laundry. "
            "The GFCI in the upstairs bathroom trips sometimes — it's on breaker 6. "
            "Reset it at the outlet first before checking the panel. "
            "If breaker 12 trips, do NOT reset it — call me, could be the compressor."
        ),
        "visibility": "internal",
        "category": "home",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "peter",
        "type": "procedure",
        "title": "What To Do If Power Goes Out",
        "content": (
            "1. Check if neighbors have power (look out the window). "
            "2. If just us: go to garage panel, look for tripped breaker (handle in middle position). "
            "3. Turn it fully OFF then back ON. "
            "4. If it trips again immediately, do NOT keep resetting — unplug everything on that circuit first. "
            "5. Flashlights are in the kitchen junk drawer and the hall closet. "
            "6. Generator is in the shed — ONLY use it outside, never in the garage. "
            "7. If whole neighborhood is out, report to power company: (555) 800-POWER."
        ),
        "visibility": "internal",
        "category": "home",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "peter",
        "type": "memory",
        "title": "Family Vacation Plans",
        "content": (
            "Hawaii trip: July 15-22. Flights booked on Hawaiian Airlines. "
            "Staying at the Marriott Ko Olina. Snorkeling tour booked for July 17. "
            "Jane wants to try surfing. Bill wants to see the volcano."
        ),
        "visibility": "internal",
        "category": "family",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "peter",
        "type": "skill",
        "title": "Licensed Electrician",
        "content": "Peter is a licensed electrician with 20 years experience, specializing in residential work.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    # ── MOLLY ──────────────────────────────────
    {
        "owner": "molly",
        "type": "procedure",
        "title": "Grandma Rose's Care Routine",
        "content": (
            "MORNING: 7am wake up, help her to bathroom. Breakfast by 7:30 — oatmeal with banana, "
            "NO dairy (lactose intolerant). 8am medications: Lisinopril 10mg (blood pressure), "
            "Metformin 500mg (diabetes) — MUST take with food. Check blood sugar with the meter "
            "in the kitchen cabinet, log it in the blue notebook.\n\n"
            "AFTERNOON: Lunch at noon, she likes soup. 2pm — check if she needs anything. "
            "She naps 2-4pm, don't disturb unless urgent.\n\n"
            "EVENING: Dinner at 6pm — low sodium. 7pm medications: Lisinopril 10mg again, "
            "Amlodipine 5mg. 8pm blood pressure check (log in blue notebook). "
            "9pm dialysis prep: set the PD machine to 2.5hr cycle, 2L bags are in the hall closet. "
            "Make sure she drinks water before starting. Machine beeps when done — "
            "drain the fluid, record the output volume.\n\n"
            "EMERGENCY: If blood sugar below 70 or above 300, call Dr. Patel immediately. "
            "If she's confused or slurring, call 911."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    {
        "owner": "molly",
        "type": "contact",
        "title": "Grandma Rose's Medical Contacts",
        "content": (
            "Primary care: Dr. Sarah Kim, (555) 234-5678, Riverside Medical, M-F 8am-5pm. "
            "Cardiologist: Dr. Raj Patel, (555) 345-6789, Heart Center, T/Th 9am-4pm. "
            "Nephrologist: Dr. Lisa Chen, (555) 456-7890, Dialysis Center, M/W/F. "
            "Pharmacy: CVS on Main St, (555) 567-8901, auto-refill is set up. "
            "Emergency: 911. Poison control: (800) 222-1222."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    {
        "owner": "molly",
        "type": "schedule",
        "title": "Molly's Austin Work Trip",
        "content": (
            "Austin TX, Feb 18-21. Flight: AA1247 departs 6:15am Tuesday from SFO. "
            "Hotel: Marriott Downtown Austin, confirmation #MR8834721. "
            "Client meetings: Wed 9am-4pm at their office (123 Congress Ave). "
            "Return flight: AA1892 departs 5:30pm Thursday, home by 9pm. "
            "Peter handles grandma's care while I'm gone. Kids' carpools are set."
        ),
        "visibility": "internal",
        "category": "family",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "molly",
        "type": "schedule",
        "title": "Q4 Report Deadline",
        "content": (
            "Q4 project status report due Friday Feb 14. Need inputs from Kyle on API migration "
            "timeline and from Sarah on design review. Template is in the shared Google Drive. "
            "Submit via Jira ticket PM-4521."
        ),
        "visibility": "internal",
        "category": "work",
        "networks": ["TechCorp PM Team"],
    },
    {
        "owner": "molly",
        "type": "skill",
        "title": "Project Manager",
        "content": "Molly is a senior project manager at TechCorp, 12 years in tech.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    {
        "owner": "molly",
        "type": "preference",
        "title": "Molly's Personal Journal",
        "content": (
            "Feeling overwhelmed managing grandma's care and work. Thinking about asking "
            "Peter if we should look into a part-time home aide. Haven't told the kids yet "
            "that grandma's kidney function is declining. Dr. Chen said 6-12 months before "
            "we need to discuss options."
        ),
        "visibility": "private",
        "category": "personal",
        "networks": [],
    },
    # ── JANE ───────────────────────────────────
    {
        "owner": "jane",
        "type": "schedule",
        "title": "Jane's Weekly Schedule",
        "content": (
            "School: M-F 7:45am-2:30pm at Lincoln High. "
            "Soccer practice: T/Th 3:30-5pm at school field. "
            "Art club: Wed 3-4:30pm. "
            "SAT prep: Saturday 10am-noon at Kumon on Oak St."
        ),
        "visibility": "internal",
        "category": "family",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "jane",
        "type": "memory",
        "title": "Jane's Lost Wallet",
        "content": (
            "Jane left her wallet on the kitchen counter before school Tuesday morning. "
            "It has her school ID, library card, and $23 cash."
        ),
        "visibility": "internal",
        "category": "family",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "jane",
        "type": "preference",
        "title": "Jane's Public Bio",
        "content": "10th grader at Lincoln High. Plays midfield on varsity soccer. Loves watercolor painting.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    {
        "owner": "jane",
        "type": "memory",
        "title": "Jane's Diary",
        "content": "Jane has a crush on Marcus from calculus class. She hasn't told anyone.",
        "visibility": "private",
        "category": "personal",
        "networks": [],
    },
    # ── BILL ───────────────────────────────────
    {
        "owner": "bill",
        "type": "schedule",
        "title": "Bill's Weekly Schedule",
        "content": (
            "School: M-F 8am-2:45pm at Roosevelt Middle. "
            "Soccer practice: M/W 3:30-5pm at Riverside Park. "
            "Game days: Saturdays 9am (various fields, check team app). "
            "Coding club: Friday 3-4pm at school."
        ),
        "visibility": "internal",
        "category": "family",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "bill",
        "type": "preference",
        "title": "Bill's Allergies and Medical",
        "content": (
            "Bill is lactose intolerant — can have Lactaid milk and aged cheeses (parmesan, cheddar ok) "
            "but NOT soft cheeses, regular milk, or ice cream. His EpiPen (peanut allergy) is in the "
            "kitchen drawer next to the fridge. Backup EpiPen is in his school backpack. "
            "Allergist: Dr. Wong, (555) 678-9012."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    {
        "owner": "bill",
        "type": "skill",
        "title": "Bill's Bio",
        "content": "8th grader at Roosevelt Middle. Into coding (learning Python), gaming, and soccer.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    {
        "owner": "bill",
        "type": "memory",
        "title": "Bill's Report Card",
        "content": "Bill got a D+ in English this semester. Parents don't know yet. He's worried about it.",
        "visibility": "private",
        "category": "personal",
        "networks": [],
    },
    # ── PETER'S DETAILED MEDICAL DATA ──
    {
        "owner": "peter",
        "type": "memory",
        "title": "Peter's Surgical History",
        "content": (
            "Appendectomy in 2018 at Riverside General — surgery performed by Dr. Torres, "
            "no complications, discharged same day. Wisdom teeth extraction 2005. "
            "Shoulder arthroscopy 2012 (rotator cuff repair, left shoulder) — full recovery "
            "after 4 months of physical therapy. Pre-op bloodwork always normal. "
            "No adverse reactions to general anesthesia. No family history of surgical complications."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    {
        "owner": "peter",
        "type": "memory",
        "title": "Peter's Prescription Details",
        "content": (
            "Current prescription: Atorvastatin 20mg daily for cholesterol management, "
            "started June 2024 after routine physical showed LDL at 165. Refill at CVS on "
            "Main St, auto-refill enabled. Previous medication: tried Rosuvastatin 10mg first "
            "but switched due to muscle aches. No other current prescriptions. "
            "OTC supplements: fish oil 1000mg and multivitamin daily."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    {
        "owner": "peter",
        "type": "memory",
        "title": "Peter's Chronic Conditions",
        "content": (
            "Mild hypercholesterolemia — diagnosed 2024, managed with Atorvastatin. "
            "Condition is improving: LDL dropped from 165 to 128 as of October 2025 physical. "
            "No hypertension. No diabetes. BMI 27.2 (slightly overweight). "
            "Family history: father had heart attack at 62, mother has type 2 diabetes. "
            "Monitoring cardiac risk factors annually. EKG normal as of last checkup."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    # ── FAMILY MEDICAL RECORDS (The Johnsons) ──
    {
        "owner": "peter",
        "type": "preference",
        "title": "Peter's Medical Info",
        "content": (
            "Blood type: O+. Height: 5'11\", Weight: 195 lbs. "
            "Prescription: Atorvastatin 20mg daily (cholesterol), refill at CVS. "
            "No known drug allergies. Had appendectomy 2018. "
            "Primary care: Dr. Torres, Riverside Medical. "
            "Insurance: Blue Cross PPO, Member ID: BCX-447281. "
            "Last physical: October 2025, all clear. Cholesterol trending down."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    {
        "owner": "molly",
        "type": "preference",
        "title": "Molly's Medical Info",
        "content": (
            "Blood type: A-. Height: 5'6\", Weight: 140 lbs. "
            "Prescription: Sertraline 50mg daily (anxiety), Vitamin D 2000 IU. "
            "Allergic to sulfa antibiotics — causes rash. "
            "Primary care: Dr. Torres, Riverside Medical. "
            "OB/GYN: Dr. Martinez, (555) 789-0123. "
            "Insurance: Blue Cross PPO, Member ID: BCX-447282. "
            "Last mammogram: June 2025, normal. Thyroid checked annually."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    {
        "owner": "jane",
        "type": "preference",
        "title": "Jane's Medical Info",
        "content": (
            "Blood type: A+. Height: 5'5\", Weight: 125 lbs. Age: 16. "
            "Prescription: Cetirizine 10mg daily (seasonal allergies). "
            "Had ACL tear repair left knee, March 2024 — cleared for full activity Sept 2024. "
            "Wears contacts: -2.50 both eyes, Acuvue Oasys. "
            "Pediatrician: Dr. Nakamura, Lincoln Pediatrics, (555) 890-1234. "
            "Insurance: Blue Cross PPO (under Peter), Dependent ID: BCX-447281-D1. "
            "Tetanus booster due: March 2026."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    {
        "owner": "bill",
        "type": "preference",
        "title": "Bill's Full Medical Record",
        "content": (
            "Blood type: O+. Height: 5'2\", Weight: 105 lbs. Age: 14. "
            "CRITICAL ALLERGIES: Peanuts (anaphylaxis) — EpiPen required. "
            "Lactose intolerant (not life-threatening). "
            "Prescription: Montelukast 10mg daily (asthma prevention), "
            "Albuterol inhaler as needed (in backpack and kitchen drawer). "
            "Pediatrician: Dr. Nakamura, Lincoln Pediatrics, (555) 890-1234. "
            "Allergist: Dr. Wong, (555) 678-9012 — next appointment March 15. "
            "Insurance: Blue Cross PPO (under Peter), Dependent ID: BCX-447281-D2. "
            "School nurse has copies of allergy action plan and inhaler authorization."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    {
        "owner": "molly",
        "type": "procedure",
        "title": "Grandma Rose's Full Medical Profile",
        "content": (
            "Blood type: B+. Age: 78. Weight: 135 lbs. "
            "CONDITIONS: Type 2 diabetes, hypertension, chronic kidney disease (stage 3b), "
            "mild cognitive impairment, osteoarthritis in both knees. "
            "MEDICATIONS (current): "
            "- Lisinopril 10mg 2x daily (7am, 7pm) — blood pressure "
            "- Metformin 500mg 2x daily (8am, 6pm) — diabetes, MUST take with food "
            "- Amlodipine 5mg 1x daily (7pm) — blood pressure "
            "- Calcitriol 0.25mcg 1x daily — kidney/bone health "
            "- Sevelamer 800mg 3x daily with meals — phosphorus binder "
            "- Erythropoietin injection weekly (Monday, administered by visiting nurse) "
            "ALLERGIES: Penicillin (hives), lactose intolerant. "
            "DNR on file — copy in the blue folder in the hall closet. "
            "Medicare ID: 1EG4-TE5-MK72. Supplemental: AARP United #UHG-99421."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    {
        "owner": "peter",
        "type": "contact",
        "title": "Family Emergency Contacts",
        "content": (
            "Peter cell: (555) 111-2222. Molly cell: (555) 111-3333. "
            "Neighbor (backup key): Linda Chen, (555) 222-4444, 45 Oak St. "
            "Poison Control: (800) 222-1222. "
            "Plumber (emergency): Mike's Plumbing, (555) 333-5555. "
            "Vet (dog, Biscuit): Riverside Animal Hospital, (555) 444-6666. "
            "Insurance agent: Tom Keane, State Farm, (555) 555-7777. "
            "Family lawyer: Patricia Gomez, (555) 666-8888."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["The Johnsons"],
    },
    # ── PROACTIVE SCENARIOS ─────────────────────
    {
        "owner": "peter",
        "type": "schedule",
        "title": "Grandma Rose's Visit",
        "content": (
            "Grandma Rose visiting Feb 20-27. Need to prepare guest room, stock low-sodium food, "
            "set up dialysis machine. Molly handles medical prep, I handle house prep."
        ),
        "visibility": "internal",
        "category": "family",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "molly",
        "type": "schedule",
        "title": "Johnson Family BBQ",
        "content": (
            "Annual BBQ March 8. Need cleaners March 7. Expecting 30 guests. Budget $500 for cleaning. "
            "Peter's on the grill. Remember Bill's peanut allergy."
        ),
        "visibility": "internal",
        "category": "family",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "molly",
        "type": "memory",
        "title": "Bill Needs SAT Prep Help",
        "content": (
            "Bill's practice SAT: 1050, needs 1200+ for state schools. Struggling with reading comprehension. "
            "Look into tutors near Roosevelt Middle. Budget up to $60/hr."
        ),
        "visibility": "internal",
        "category": "family",
        "networks": ["The Johnsons"],
    },
    # ── KYLE ───────────────────────────────────
    {
        "owner": "kyle",
        "type": "skill",
        "title": "Open Source Contributor",
        "content": "Maintaining react-query-builder on GitHub (2k stars). Looking for contributors who know TypeScript and testing.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    {
        "owner": "kyle",
        "type": "skill",
        "title": "API Migration Lead",
        "content": (
            "Leading the REST to GraphQL migration for TechCorp's customer portal. "
            "Timeline: Phase 1 (auth endpoints) done, Phase 2 (user data) in progress, "
            "Phase 3 (reporting) starts March. Using Apollo Federation."
        ),
        "visibility": "internal",
        "category": "work",
        "networks": ["TechCorp PM Team"],
    },
    {
        "owner": "kyle",
        "type": "skill",
        "title": "Software Engineer",
        "content": "Kyle is a senior software engineer at TechCorp, specializing in backend systems and API design.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    # ── GRANDMA ROSE ──────────────────────────
    {
        "owner": "grandmarose",
        "type": "preference",
        "title": "Rose's Medical Info",
        "content": (
            "Blood type: B+. Age: 78. Height: 5'4\", Weight: 135 lbs. "
            "Primary care: Dr. Sarah Kim, (555) 234-5678, Riverside Medical. "
            "Cardiologist: Dr. Raj Patel, (555) 345-6789, Heart Center. "
            "Nephrologist: Dr. Angela Wu, (555) 456-7890, Kidney Care Associates. "
            "Medicare ID: 1EG4-TE5-MK72. Supplemental: AARP United #UHG-99421."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["Rose's Care Circle"],
    },
    {
        "owner": "grandmarose",
        "type": "procedure",
        "title": "Rose's Medications",
        "content": (
            "Current medications (as of Jan 2026): "
            "- Lisinopril 10mg 2x daily (7am, 7pm) — blood pressure "
            "- Metformin 500mg 2x daily (8am, 6pm) — diabetes, MUST take with food "
            "- Amlodipine 5mg 1x daily (7pm) — blood pressure "
            "- Calcitriol 0.25mcg 1x daily — kidney/bone health "
            "- Sevelamer 800mg 3x daily with meals — phosphorus binder "
            "- Erythropoietin injection weekly (Monday, administered by visiting nurse) "
            "Pharmacy: CVS Main St, auto-refill enabled for Lisinopril and Metformin."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["Rose's Care Circle"],
    },
    {
        "owner": "grandmarose",
        "type": "preference",
        "title": "Rose's Allergies",
        "content": (
            "ALLERGIES: Penicillin (causes hives — documented reaction 2018, use alternatives). "
            "Lactose intolerant — no dairy, uses oat milk. "
            "Mild reaction to sulfa drugs (rash) — avoid if possible. "
            "No known food allergies besides lactose."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["Rose's Care Circle"],
    },
    {
        "owner": "grandmarose",
        "type": "procedure",
        "title": "Rose's Chronic Conditions",
        "content": (
            "Type 2 diabetes — diagnosed 2012, managed with Metformin, A1C stable at 6.8. "
            "Hypertension — diagnosed 2008, managed with Lisinopril + Amlodipine, BP target <140/90. "
            "Chronic kidney disease (stage 3b) — GFR 38, monitored quarterly. "
            "Mild cognitive impairment — occasional memory issues, no dementia diagnosis. "
            "Osteoarthritis in both knees — uses walker for longer distances. "
            "DNR on file — copy in the blue folder in the hall closet."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["Rose's Care Circle"],
    },
    {
        "owner": "grandmarose",
        "type": "memory",
        "title": "Rose's Surgical History",
        "content": (
            "Left hip replacement (2019) — Dr. Martinez, Riverside General, ceramic-on-poly implant, "
            "full recovery in 8 weeks. Right knee arthroscopy (2016) — cartilage debridement, "
            "outpatient procedure at Bay Area Surgical Center. Appendectomy (1975) — no complications. "
            "Cataract surgery both eyes (2020, 2021) — successful, wears reading glasses only now. "
            "AV fistula placement left forearm (2023) — for dialysis access, functioning well. "
            "No adverse reactions to general anesthesia. Pre-op cardiac clearance always required "
            "due to hypertension — last clearance Dec 2025."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["Rose's Care Circle"],
    },
    {
        "owner": "grandmarose",
        "type": "preference",
        "title": "Rose's Blood Pressure & Dialysis Log",
        "content": (
            "Blood pressure (last 3 readings): 138/82 (Feb 10), 142/88 (Feb 7), 135/80 (Feb 3). "
            "Target: <140/90. Trending stable. "
            "Dialysis schedule: Tuesday, Thursday, Saturday — 6am-10am at Riverside Dialysis Center. "
            "Current dry weight: 135 lbs. AV fistula left forearm — good thrill and bruit. "
            "Last labs (Feb 5): Potassium 4.8, Phosphorus 5.2 (slightly high), BUN 48, Creatinine 3.1, "
            "GFR 38. Hemoglobin 10.8 (stable on Erythropoietin)."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["Rose's Care Circle"],
    },
    {
        "owner": "grandmarose",
        "type": "contact",
        "title": "Rose's Emergency Contacts",
        "content": (
            "Daughter: Molly Johnson, (555) 111-3333. "
            "Son-in-law: Peter Johnson, (555) 111-2222. "
            "Friend & neighbor: Dorothy Chen, (555) 333-2222. "
            "Nephrologist (urgent): Dr. Angela Wu, (555) 456-7890. "
            "Dialysis center: Riverside Dialysis, (555) 567-8901, T/Th/Sat 6am-12pm."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["Rose's Care Circle"],
    },
    {
        "owner": "grandmarose",
        "type": "preference",
        "title": "Rose's Daily Routine",
        "content": (
            "Wake at 7am. Breakfast: oatmeal with banana (no dairy — lactose intolerant). "
            "Morning walk in the garden if weather permits. Bridge club Thursdays at 2pm. "
            "Nap 2-4pm. Dinner at 6pm — low sodium. Bed by 9:30pm after dialysis prep."
        ),
        "visibility": "internal",
        "category": "health",
        "emergency_accessible": True,
        "networks": ["Rose's Care Circle"],
    },
    {
        "owner": "grandmarose",
        "type": "memory",
        "title": "Rose's Garden Tips",
        "content": (
            "Best time to plant tomatoes in Bay Area: April. Use raised beds — easier on my knees. "
            "Compost from the community garden is free on Saturdays. My prize-winning roses are "
            "English Heritage variety, need deadheading every two weeks."
        ),
        "visibility": "open",
        "category": "general",
        "can_reshare": True,
        "networks": [],
    },
    {
        "owner": "grandmarose",
        "type": "schedule",
        "title": "Rose's Visiting Plans",
        "content": (
            "Visiting the Johnsons Feb 20-27. Molly set up the guest room. "
            "Need dialysis machine — Peter bringing it over Feb 19. "
            "Dorothy will water my plants while I'm away."
        ),
        "visibility": "internal",
        "category": "family",
        "networks": ["Rose's Care Circle", "The Johnsons"],
    },
    # ── LINDA CHEN (neighbor) ─────────────────
    {
        "owner": "linda",
        "type": "skill",
        "title": "Architect & Community Organizer",
        "content": (
            "Licensed architect at Chen Design. Specializing in sustainable residential design. "
            "Also organize the Riverside community garden and annual block party."
        ),
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    {
        "owner": "linda",
        "type": "schedule",
        "title": "Riverside Block Party",
        "content": (
            "Annual Riverside block party: March 15, 2-6pm on Oak Street. "
            "Need volunteers for setup at noon. Potluck — sign up sheet on the community board. "
            "Live music this year (Peter offered to play guitar!)."
        ),
        "visibility": "internal",
        "category": "general",
        "networks": ["Riverside Neighbors"],
    },
    {
        "owner": "linda",
        "type": "preference",
        "title": "Neighborhood Safety Notes",
        "content": (
            "Package thefts reported on Elm St last week — ring cameras recommended. "
            "Street sweeping: Tuesdays (even side) and Thursdays (odd side). "
            "Backup key for the Johnsons at our house (45 Oak St)."
        ),
        "visibility": "internal",
        "category": "home",
        "networks": ["Riverside Neighbors"],
    },
    # ── AMY TORRES (Jane's friend) ────────────
    {
        "owner": "amy",
        "type": "schedule",
        "title": "Soccer Season Schedule",
        "content": (
            "Lincoln High varsity soccer: Practice T/Th 3:30-5pm. "
            "Games: Saturdays, alternating home/away. Next game: Feb 15 vs. Lakewood (home). "
            "Playoffs start March 1. Team dinner at Olive Garden after each win."
        ),
        "visibility": "internal",
        "category": "general",
        "networks": ["Lincoln High Soccer"],
    },
    {
        "owner": "amy",
        "type": "preference",
        "title": "Amy's Bio",
        "content": "Varsity soccer co-captain with Jane. Planning to study marine biology at UCSC. Volunteers at the aquarium on weekends.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    # ── MARCUS WILLIAMS (Bill's friend) ───────
    {
        "owner": "marcus",
        "type": "skill",
        "title": "Coding Club Projects",
        "content": (
            "Current project: Minecraft mod that adds real-world physics (gravity, buoyancy). "
            "Using Java and Forge API. Next science fair project: AI that plays tic-tac-toe "
            "using minimax algorithm. Teaching Bill Python basics on Fridays."
        ),
        "visibility": "internal",
        "category": "general",
        "networks": ["Roosevelt Coding Club"],
    },
    {
        "owner": "marcus",
        "type": "schedule",
        "title": "Coding Club Schedule",
        "content": (
            "Roosevelt Coding Club: Fridays 3-4pm in the computer lab. "
            "Hackathon coming up March 22 — need 3-person teams. "
            "Bill and I are looking for a third member."
        ),
        "visibility": "internal",
        "category": "general",
        "networks": ["Roosevelt Coding Club"],
    },
    {
        "owner": "marcus",
        "type": "skill",
        "title": "Marcus's Bio",
        "content": "8th grader at Roosevelt Middle. Coding club president. Building Minecraft mods and AI projects. Science fair county winner 2025.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    # ── DOROTHY PARK (Rose's friend) ──────────
    {
        "owner": "dorothy",
        "type": "preference",
        "title": "Dorothy's Community Activities",
        "content": (
            "Volunteer at Riverside Community Center M/W/F 10am-2pm. Run the book club (first Tuesday each month). "
            "Bridge club with Rose on Thursdays. Rose and I have been friends for 40 years — "
            "we taught at the same school."
        ),
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    {
        "owner": "dorothy",
        "type": "schedule",
        "title": "Community Center Events",
        "content": (
            "Feb events: Valentine's craft fair Feb 14. Movie night Feb 21 (showing Casablanca). "
            "March: Spring gardening workshop March 1 (Linda Chen leading). "
            "Tai chi classes starting March 10, Mondays 9am."
        ),
        "visibility": "internal",
        "category": "general",
        "networks": ["Riverside Bridge Club"],
    },
    # ── HEALTHCARE PRACTITIONERS ───────────────
    {
        "owner": "dr_lee",
        "type": "skill",
        "title": "Dr. Lee's Credentials",
        "content": "Board certified in Emergency Medicine (ABEM). MD from UCSF, residency at Stanford. NPI: 1234567890. Specializes in cardiac emergencies and trauma.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    {
        "owner": "dr_lee",
        "type": "procedure",
        "title": "ER Shift Schedule",
        "content": "Current rotation: Mon/Wed/Fri 7am-7pm, alternating weekends. On-call for cardiac emergencies. Backup: Dr. Patel (cardiology).",
        "visibility": "internal",
        "category": "work",
        "networks": ["Riverside ER Team"],
    },
    {
        "owner": "nurse_davis",
        "type": "skill",
        "title": "Nurse Davis's Credentials",
        "content": "RN, BSN. 8 years ER experience. Triage specialist. BLS/ACLS/PALS certified. Riverside General Hospital employee since 2018.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    {
        "owner": "nurse_davis",
        "type": "procedure",
        "title": "Triage Protocols",
        "content": "Standard triage: check vitals, allergies, current medications, chief complaint. For cardiac: immediate 12-lead EKG, check for STEMI. For anaphylaxis: check allergy history, administer epi if needed.",
        "visibility": "internal",
        "category": "work",
        "networks": ["Riverside ER Team"],
    },
    {
        "owner": "emt_johnson",
        "type": "skill",
        "title": "EMT Johnson's Credentials",
        "content": "NREMT-Paramedic. Advanced Life Support certified. 6 years field experience with Riverside City Ambulance. Specializes in cardiac and trauma response.",
        "visibility": "open",
        "category": "general",
        "networks": [],
    },
    {
        "owner": "emt_johnson",
        "type": "procedure",
        "title": "Field Assessment Protocol",
        "content": "On-scene: ABCs first. Check for medical alert bracelet/necklace. Query TrustMesh for patient data if identity confirmed. Critical info needed: allergies (especially drug allergies), DNR status, blood type, emergency contacts.",
        "visibility": "internal",
        "category": "work",
        "networks": ["Riverside ER Team"],
    },
    # ── BAY AREA MUSIC (Peter's hobby) ────────
    {
        "owner": "peter",
        "type": "preference",
        "title": "Peter's Music Interests",
        "content": (
            "Play guitar — mostly classic rock (Hendrix, Clapton, Santana). "
            "Looking for jam partners in Riverside area. Have a Fender Stratocaster and a Marshall amp. "
            "Open to blues, rock, and funk. Practice in the garage weekday evenings."
        ),
        "visibility": "internal",
        "category": "personal",
        "networks": ["Bay Area Music Lovers"],
    },
]


async def seed():
    """Seed the database with demo data."""
    print("\n\u2550\u2550\u2550 TrustMesh Seed \u2550\u2550\u2550\n")

    await drop_db()
    await init_db()
    reset_collection()

    # Import vault_keys from main to populate
    from src.main import vault_keys

    service_capsule_count = sum(len(sp.get("capsules", [])) for sp in SERVICE_PROVIDERS)
    total_capsules = len(CAPSULES) + service_capsule_count

    async with async_session() as db:
        user_map: dict[str, User] = {}
        network_map: dict[str, Network] = {}
        network_keys: dict[str, bytes] = {}  # network_id -> plaintext key

        # ── Step 1: Create Users ──
        print(f"Step 1/7: Creating {len(USERS)} users + vault keys...")
        for u in USERS:
            vault_master_key = generate_key()
            derived_key, salt = derive_vault_key(DEMO_PASSWORD)
            encrypted_vault_key = encrypt(vault_master_key, derived_key)

            user = User(
                username=u["username"],
                display_name=u["display_name"],
                bio=u["bio"],
                is_demo=True,
                profile_data=json.dumps(u["profile_data"]) if u.get("profile_data") else None,
                vault_key_salt=salt,
                encrypted_vault_key=encrypted_vault_key,
                pin_hash=hash_pin("1234"),  # Default demo PIN
            )
            db.add(user)
            await db.flush()
            user_map[u["username"]] = user
            vault_keys[user.id] = vault_master_key

            # Generate ed25519 keypair for agent identity
            private_key_bytes, public_key_bytes = generate_ed25519_keypair()
            agent_did = public_key_to_did(public_key_bytes)
            encrypted_privkey = encrypt(private_key_bytes, vault_master_key)

            agent = Agent(
                owner_id=user.id,
                name=f"{u['display_name']}'s Agent",
                personality=u["agent_personality"],
                public_key=public_key_bytes,
                encrypted_private_key=encrypted_privkey,
                did=agent_did,
            )
            db.add(agent)
            key_preview = vault_master_key[:4].hex()
            print(f"  \u2713 {u['display_name']} \u2014 vault: {key_preview}..., DID: {agent_did[:30]}...")

        # ── Step 2: Create Service Providers ──
        print(f"\nStep 2/7: Creating {len(SERVICE_PROVIDERS)} service providers...")
        for sp in SERVICE_PROVIDERS:
            vault_master_key = generate_key()
            derived_key, salt = derive_vault_key(DEMO_PASSWORD)
            encrypted_vault_key = encrypt(vault_master_key, derived_key)

            service_user = User(
                username=sp["username"],
                display_name=sp["display_name"],
                bio=sp["bio"],
                user_type=sp.get("user_type", "organization"),
                is_demo=True,
                profile_data=json.dumps(sp.get("profile_data")) if sp.get("profile_data") else None,
                vault_key_salt=salt,
                encrypted_vault_key=encrypted_vault_key,
                agent_personality=sp["agent_personality"],
            )
            db.add(service_user)
            await db.flush()
            user_map[sp["username"]] = service_user
            vault_keys[service_user.id] = vault_master_key

            # Generate ed25519 keypair for service agent identity
            private_key_bytes, public_key_bytes = generate_ed25519_keypair()
            agent_did = public_key_to_did(public_key_bytes)
            encrypted_privkey = encrypt(private_key_bytes, vault_master_key)

            agent = Agent(
                owner_id=service_user.id,
                name=f"{sp['display_name']} Agent",
                personality=sp["agent_personality"],
                public_key=public_key_bytes,
                encrypted_private_key=encrypted_privkey,
                did=agent_did,
            )
            db.add(agent)
            print(f"  \u2713 {sp['display_name']} \u2014 DID: {agent_did[:30]}...")

        # ── Step 3: Create Connections ──
        print(f"\nStep 3/7: Establishing {len(CONNECTIONS)} connections...")
        for from_name, to_name, conn_ctx in CONNECTIONS:
            conn = Connection(
                from_user_id=user_map[from_name].id,
                to_user_id=user_map[to_name].id,
                context=conn_ctx,
                status="accepted",
                accepted_at=datetime.now(timezone.utc),
            )
            db.add(conn)
            print(f"  \u2713 {from_name} \u2194 {to_name} ({conn_ctx})")

        # ── Step 4: Create Networks with proper key wrapping ──
        print(f"\nStep 4/7: Creating {len(NETWORKS)} networks with key wrapping...")
        for n in NETWORKS:
            network_key = generate_key()
            owner_vault_key = vault_keys[user_map[n["owner"]].id]
            encrypted_key = encrypt(network_key, owner_vault_key)

            network = Network(
                owner_id=user_map[n["owner"]].id,
                name=n["name"],
                description=n.get("description", ""),
                network_type=n["type"],
                is_public=n.get("is_public", False),
                join_policy=n.get("join_policy", "invite_only"),
                context=n.get("context", "personal"),
                encrypted_network_key=encrypted_key,
            )
            db.add(network)
            await db.flush()
            network_map[n["name"]] = network
            network_keys[network.id] = network_key

            for member_name in n["members"]:
                member_vault_key = vault_keys[user_map[member_name].id]
                membership = NetworkMembership(
                    network_id=network.id,
                    user_id=user_map[member_name].id,
                    role="owner" if member_name == n["owner"] else "member",
                    encrypted_network_key=encrypt(network_key, member_vault_key),
                )
                db.add(membership)
            print(f"  \u2713 {n['name']} \u2014 key wrapped for {len(n['members'])} members")

        # ── Step 5: Create Capsules ──
        print(f"\nStep 5/7: Creating {total_capsules} capsules with encryption...")
        # Work networks for auto-context detection
        work_networks = {n["name"] for n in NETWORKS if n.get("context") == "work"}

        capsule_count = 0
        for c in CAPSULES:
            owner = user_map[c["owner"]]
            vault_key = vault_keys[owner.id]

            # Infer context: explicit > network-based > default personal
            if "context" in c:
                ctx = c["context"]
            elif any(n in work_networks for n in c.get("networks", [])):
                ctx = "work"
            else:
                ctx = "personal"

            visibility = c.get("visibility", "private")
            emergency_accessible = c.get("emergency_accessible", False)
            can_reshare = c.get("can_reshare", False)

            capsule = KnowledgeCapsule(
                owner_id=owner.id,
                capsule_type=c["type"],
                title=c["title"],
                content_encrypted=encrypt_text(c["content"], vault_key),
                visibility=visibility,
                emergency_accessible=emergency_accessible,
                can_reshare=can_reshare,
                category=c.get("category", ""),
                context=ctx,
                freshness="permanent" if c["type"] in ("skill", "procedure", "preference", "contact") else "temporary",
            )
            db.add(capsule)
            await db.flush()

            # Network access
            for net_name in c.get("networks", []):
                if net_name in network_map:
                    db.add(CapsuleNetworkAccess(
                        capsule_id=capsule.id,
                        network_id=network_map[net_name].id,
                    ))

            # Embed for semantic search
            upsert_capsule_embedding(
                capsule.id,
                f"{c['title']}: {c['content']}",
                {"capsule_id": capsule.id, "owner_id": owner.id, "visibility": visibility},
            )
            capsule_count += 1
            print(f"  \u2713 [{visibility}] {c['title']} ({c['owner']})")

        # Service provider capsules
        for sp in SERVICE_PROVIDERS:
            sp_user = user_map[sp["username"]]
            sp_vault_key = vault_keys[sp_user.id]
            for cap in sp.get("capsules", []):
                cap_visibility = cap.get("visibility", "open")
                capsule = KnowledgeCapsule(
                    owner_id=sp_user.id,
                    capsule_type=cap["type"],
                    title=cap["title"],
                    content_encrypted=encrypt_text(cap["content"], sp_vault_key),
                    visibility=cap_visibility,
                    category=cap.get("category", "general"),
                    freshness="permanent",
                )
                db.add(capsule)
                await db.flush()
                upsert_capsule_embedding(
                    capsule.id,
                    f"{cap['title']}: {cap['content']}",
                    {"capsule_id": capsule.id, "owner_id": sp_user.id, "visibility": cap_visibility},
                )
                capsule_count += 1
                print(f"  \u2713 [{cap_visibility}] {cap['title']} ({sp['username']})")

        # ── Step 5b: Create Ghost User for Cross-Pod Demo ──
        print("\nStep 5b: Creating ghost user for cross-pod demo...")
        ghost = User(
            username="remote:alex@partner-pod.local",
            display_name="Alex Chen (PartnerCo)",
            bio="Remote engineer on the PartnerCo pod",
            is_discoverable=False,
            is_demo=False,
            is_remote=True,
            remote_pod_url="http://localhost:8001",
            remote_did="did:key:z6MkPartnerAlex",
        )
        db.add(ghost)
        await db.flush()
        user_map["remote:alex@partner-pod.local"] = ghost

        # Add ghost to TechCorp PM Team (simulating cross-pod pool membership)
        techcorp_network = network_map["TechCorp PM Team"]
        ghost_membership = NetworkMembership(
            network_id=techcorp_network.id,
            user_id=ghost.id,
            role="remote_member",
        )
        db.add(ghost_membership)

        # Create auto-accepted connections between ghost and local pool members
        for member_name in ["molly", "kyle"]:
            conn = Connection(
                from_user_id=ghost.id,
                to_user_id=user_map[member_name].id,
                context="both",
                status="accepted",
                accepted_at=datetime.now(timezone.utc),
            )
            db.add(conn)
        print(f"  \u2713 Ghost: {ghost.username} \u2014 DID: {ghost.remote_did}, pool: TechCorp PM Team")

        # ── Step 6: Create Sharing Delegates ──
        print("\nStep 6/7: Seeding sharing delegates...")
        delegates = [
            ("peter", "molly", "health"),
            ("molly", "peter", "family"),
        ]
        for owner_name, delegate_name, category in delegates:
            delegate = SharingDelegate(
                owner_id=user_map[owner_name].id,
                delegate_user_id=user_map[delegate_name].id,
                category=category,
            )
            db.add(delegate)
            print(f"  \u2713 {owner_name} \u2192 {delegate_name} ({category} delegate)")

        await db.flush()

        # ── Step 7: Verify ──
        print("\nStep 7/7: Committing to database...")
        await db.commit()

    # ── Summary ──
    total_users = len(USERS) + len(SERVICE_PROVIDERS)
    print(f"\n\u2550\u2550\u2550 Summary \u2550\u2550\u2550")
    print(f"  {total_users} users ({len(USERS)} people + {len(SERVICE_PROVIDERS)} services)")
    print(f"  {len(CONNECTIONS)} connections")
    print(f"  {len(NETWORKS)} networks (all key-wrapped)")
    print(f"  {capsule_count} encrypted capsules")
    print(f"  {len(delegates)} sharing delegates")
    print(f"  {total_users} ed25519 keypairs + DIDs")
    print(f"  {len(vault_keys)} AES-256 vault keys loaded\n")


if __name__ == "__main__":
    asyncio.run(seed())
