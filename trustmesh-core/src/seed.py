"""Seed script: populate the database with demo data for the Johnson family scenario."""

import asyncio
from datetime import datetime, timezone

from src.crypto import derive_vault_key, encrypt, encrypt_text, generate_key
from src.database import drop_db, init_db, async_session
from src.embeddings import reset_collection, upsert_capsule_embedding
from src.models import (
    Agent,
    CapsuleNetworkAccess,
    Connection,
    KnowledgeCapsule,
    Network,
    NetworkMembership,
    User,
)

# Shared password for demo (simplified for hackathon)
DEMO_PASSWORD = "trustmesh-demo"

USERS = [
    {
        "username": "peter",
        "display_name": "Peter Johnson",
        "bio": "Licensed electrician, dad of two. Ask me about home electrical.",
        "agent_personality": "Helpful and practical. Expert in electrical work and home safety. Protective dad.",
    },
    {
        "username": "molly",
        "display_name": "Molly Johnson",
        "bio": "Project manager at TechCorp. Mom, caretaker for Grandma Rose.",
        "agent_personality": "Organized and caring. Manages work projects and family care duties. Very detail-oriented about grandma's medical needs.",
    },
    {
        "username": "jane",
        "display_name": "Jane Johnson",
        "bio": "10th grader at Lincoln High. Soccer and art.",
        "agent_personality": "Friendly and energetic. Shares school and activity info openly with family.",
    },
    {
        "username": "bill",
        "display_name": "Bill Johnson",
        "bio": "8th grader. Coding, gaming, and soccer.",
        "agent_personality": "Casual and helpful. Shares school and activity info with family.",
    },
    {
        "username": "kyle",
        "display_name": "Kyle Rivera",
        "bio": "Software engineer at TechCorp. Molly's colleague.",
        "agent_personality": "Professional and technical. Shares work-related info with teammates.",
    },
]

CONNECTIONS = [
    ("peter", "molly"),
    ("peter", "jane"),
    ("peter", "bill"),
    ("molly", "jane"),
    ("molly", "bill"),
    ("molly", "kyle"),
    ("jane", "bill"),
]

NETWORKS = [
    {
        "name": "The Johnsons",
        "type": "family",
        "owner": "peter",
        "members": ["peter", "molly", "jane", "bill"],
    },
    {
        "name": "TechCorp PM Team",
        "type": "team",
        "owner": "molly",
        "members": ["molly", "kyle"],
    },
]

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
        "tier": "network",
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
        "tier": "network",
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
        "tier": "network",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "peter",
        "type": "skill",
        "title": "Licensed Electrician",
        "content": "Peter is a licensed electrician with 20 years experience, specializing in residential work.",
        "tier": "public",
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
        "tier": "network",
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
        "tier": "network",
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
        "tier": "network",
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
        "tier": "network",
        "networks": ["TechCorp PM Team"],
    },
    {
        "owner": "molly",
        "type": "skill",
        "title": "Project Manager",
        "content": "Molly is a senior project manager at TechCorp, 12 years in tech.",
        "tier": "public",
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
        "tier": "private",
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
        "tier": "network",
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
        "tier": "network",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "jane",
        "type": "preference",
        "title": "Jane's Public Bio",
        "content": "10th grader at Lincoln High. Plays midfield on varsity soccer. Loves watercolor painting.",
        "tier": "public",
        "networks": [],
    },
    {
        "owner": "jane",
        "type": "memory",
        "title": "Jane's Diary",
        "content": "Jane has a crush on Marcus from calculus class. She hasn't told anyone.",
        "tier": "private",
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
        "tier": "network",
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
        "tier": "network",
        "networks": ["The Johnsons"],
    },
    {
        "owner": "bill",
        "type": "skill",
        "title": "Bill's Bio",
        "content": "8th grader at Roosevelt Middle. Into coding (learning Python), gaming, and soccer.",
        "tier": "public",
        "networks": [],
    },
    {
        "owner": "bill",
        "type": "memory",
        "title": "Bill's Report Card",
        "content": "Bill got a D+ in English this semester. Parents don't know yet. He's worried about it.",
        "tier": "private",
        "networks": [],
    },
    # ── KYLE ───────────────────────────────────
    {
        "owner": "kyle",
        "type": "skill",
        "title": "API Migration Lead",
        "content": (
            "Leading the REST to GraphQL migration for TechCorp's customer portal. "
            "Timeline: Phase 1 (auth endpoints) done, Phase 2 (user data) in progress, "
            "Phase 3 (reporting) starts March. Using Apollo Federation."
        ),
        "tier": "network",
        "networks": ["TechCorp PM Team"],
    },
    {
        "owner": "kyle",
        "type": "skill",
        "title": "Software Engineer",
        "content": "Kyle is a senior software engineer at TechCorp, specializing in backend systems and API design.",
        "tier": "public",
        "networks": [],
    },
]


async def seed():
    """Seed the database with demo data."""
    print("Seeding TrustMesh database...")

    await drop_db()
    await init_db()
    reset_collection()

    # Import vault_keys from main to populate
    from src.main import vault_keys

    async with async_session() as db:
        user_map: dict[str, User] = {}
        network_map: dict[str, Network] = {}

        # ── Create Users ──
        for u in USERS:
            vault_master_key = generate_key()
            derived_key, salt = derive_vault_key(DEMO_PASSWORD)
            encrypted_vault_key = encrypt(vault_master_key, derived_key)

            user = User(
                username=u["username"],
                display_name=u["display_name"],
                bio=u["bio"],
                vault_key_salt=salt,
                encrypted_vault_key=encrypted_vault_key,
            )
            db.add(user)
            await db.flush()
            user_map[u["username"]] = user
            vault_keys[user.id] = vault_master_key

            agent = Agent(
                owner_id=user.id,
                name=f"{u['display_name']}'s Agent",
                personality=u["agent_personality"],
            )
            db.add(agent)
            print(f"  Created user: {u['display_name']} ({user.id})")

        # ── Create Connections ──
        for from_name, to_name in CONNECTIONS:
            conn = Connection(
                from_user_id=user_map[from_name].id,
                to_user_id=user_map[to_name].id,
                status="accepted",
                accepted_at=datetime.now(timezone.utc),
            )
            db.add(conn)
            print(f"  Connected: {from_name} <-> {to_name}")

        # ── Create Networks ──
        for n in NETWORKS:
            network_key = generate_key()
            encrypted_key = encrypt(network_key, network_key)

            network = Network(
                owner_id=user_map[n["owner"]].id,
                name=n["name"],
                network_type=n["type"],
                encrypted_network_key=encrypted_key,
            )
            db.add(network)
            await db.flush()
            network_map[n["name"]] = network

            for member_name in n["members"]:
                membership = NetworkMembership(
                    network_id=network.id,
                    user_id=user_map[member_name].id,
                    role="owner" if member_name == n["owner"] else "member",
                )
                db.add(membership)
            print(f"  Created network: {n['name']} ({', '.join(n['members'])})")

        # ── Create Capsules ──
        for c in CAPSULES:
            owner = user_map[c["owner"]]
            vault_key = vault_keys[owner.id]

            capsule = KnowledgeCapsule(
                owner_id=owner.id,
                capsule_type=c["type"],
                title=c["title"],
                content_encrypted=encrypt_text(c["content"], vault_key),
                tier=c["tier"],
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
                {"capsule_id": capsule.id, "owner_id": owner.id, "tier": c["tier"]},
            )
            print(f"  Created capsule: [{c['tier']}] {c['title']} ({c['owner']})")

        await db.commit()

    print(f"\nSeed complete! {len(USERS)} users, {len(CONNECTIONS)} connections, "
          f"{len(NETWORKS)} networks, {len(CAPSULES)} capsules.")
    print(f"Vault keys loaded for {len(vault_keys)} users.")


if __name__ == "__main__":
    asyncio.run(seed())
