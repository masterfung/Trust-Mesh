"""Per-pod seeder: generates one SQLite DB per entity for multi-pod federation.

Maps 19 entities from the Johnson family scenario to individual pods.
Each pod gets: one primary user, their agent, their capsules.
Cross-pod connections and networks are handled by the orchestrator.

Usage:
    cd trustmesh-core && uv run python -m src.seed_multi
"""

import asyncio
import json
import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.crypto import (
    derive_vault_key,
    encrypt,
    encrypt_text,
    generate_ed25519_keypair,
    generate_key,
    hash_pin,
    public_key_to_did,
)
from src.models import Agent, Base, KnowledgeCapsule, User
from src.seed import CAPSULES, DEMO_PASSWORD, SERVICE_PROVIDERS, USERS

# ── Pod definitions: maps entity key -> seed data ──
# Person pods: reuse from USERS list (matched by username)
# Org pods: reuse from SERVICE_PROVIDERS list

# Map plan names to existing seed usernames
POD_ENTITIES = {
    # People (ports 8001-8010)
    "sarah":    {"port": 8001, "username": "molly",        "type": "person"},   # "Molly" = Sarah in plan
    "mike":     {"port": 8002, "username": "peter",        "type": "person"},   # "Peter" = Mike in plan
    "emma":     {"port": 8003, "username": "jane",         "type": "person"},   # "Jane" = Emma in plan
    "grandma":  {"port": 8004, "username": "grandmarose",  "type": "person"},
    "dr_chen":  {"port": 8005, "username": "dr_lee",       "type": "person"},   # Dr. Lee = Dr. Chen in plan
    "tom":      {"port": 8006, "username": "kyle",         "type": "person"},   # Kyle = Tom the plumber in plan
    "lisa":     {"port": 8007, "username": "amy",          "type": "person"},   # Amy = Lisa Rodriguez in plan
    "priya":    {"port": 8008, "username": "dorothy",      "type": "person"},   # Dorothy = Priya Patel in plan
    "james":    {"port": 8009, "username": "nurse_davis",  "type": "person"},   # Nurse Davis = James Wilson
    "maria":    {"port": 8010, "username": "emt_johnson",  "type": "person"},   # EMT Johnson = Maria Santos
    # Organizations (ports 8011-8016)
    "techcorp":  {"port": 8011, "username": "sparkleclean",        "type": "organization"},
    "hospital":  {"port": 8012, "username": "riverside_hospital",  "type": "organization"},
    "music":     {"port": 8013, "username": "acetutor",            "type": "organization"},
    "city":      {"port": 8014, "username": "riverside_gov",       "type": "government"},
    "insurance": {"port": 8015, "username": "handypro",            "type": "organization"},
    "dance":     {"port": 8016, "username": "riverside_ambulance", "type": "organization"},
}

# Build lookup maps
_USER_MAP = {u["username"]: u for u in USERS}
_SP_MAP = {sp["username"]: sp for sp in SERVICE_PROVIDERS}

DATA_DIR = Path(__file__).parent.parent / "data" / "pods"


def _get_user_data(username: str) -> dict:
    """Get user data from either USERS or SERVICE_PROVIDERS."""
    if username in _USER_MAP:
        return _USER_MAP[username]
    if username in _SP_MAP:
        return _SP_MAP[username]
    raise ValueError(f"Unknown username: {username}")


def _get_capsules(username: str) -> list[dict]:
    """Get capsules owned by this username."""
    # Regular capsules
    caps = [c for c in CAPSULES if c["owner"] == username]
    # Service provider capsules
    for sp in SERVICE_PROVIDERS:
        if sp["username"] == username:
            for cap in sp.get("capsules", []):
                caps.append({
                    "owner": username,
                    "type": cap["type"],
                    "title": cap["title"],
                    "content": cap["content"],
                    "visibility": cap.get("visibility", "open"),
                    "category": cap.get("category", "general"),
                    "networks": [],
                })
    return caps


async def seed_pod(entity_key: str, db_path: str):
    """Create a single pod's database with one user, their agent, and their capsules."""
    entity = POD_ENTITIES[entity_key]
    username = entity["username"]
    user_data = _get_user_data(username)

    # Create engine for this specific DB
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        # Create the primary user
        vault_master_key = generate_key()
        derived_key, salt = derive_vault_key(DEMO_PASSWORD)
        encrypted_vault_key = encrypt(vault_master_key, derived_key)

        user = User(
            username=user_data["username"],
            display_name=user_data["display_name"],
            bio=user_data["bio"],
            user_type=user_data.get("user_type", entity["type"]),
            is_demo=True,
            profile_data=json.dumps(user_data["profile_data"]) if user_data.get("profile_data") else None,
            vault_key_salt=salt,
            encrypted_vault_key=encrypted_vault_key,
            pin_hash=hash_pin("1234"),
            agent_personality=user_data.get("agent_personality"),
        )
        db.add(user)
        await db.flush()

        # Create agent with ed25519 keypair
        private_key_bytes, public_key_bytes = generate_ed25519_keypair()
        agent_did = public_key_to_did(public_key_bytes)
        encrypted_privkey = encrypt(private_key_bytes, vault_master_key)

        agent = Agent(
            owner_id=user.id,
            name=f"{user_data['display_name']}'s Agent",
            personality=user_data.get("agent_personality", "Helpful and knowledgeable"),
            public_key=public_key_bytes,
            encrypted_private_key=encrypted_privkey,
            did=agent_did,
        )
        db.add(agent)

        # Create capsules
        capsules = _get_capsules(username)
        for c in capsules:
            capsule = KnowledgeCapsule(
                owner_id=user.id,
                capsule_type=c["type"],
                title=c["title"],
                content_encrypted=encrypt_text(c["content"], vault_master_key),
                visibility=c.get("visibility", "private"),
                emergency_accessible=c.get("emergency_accessible", False),
                can_reshare=c.get("can_reshare", False),
                category=c.get("category", ""),
                context=c.get("context", "personal"),
                freshness="permanent" if c["type"] in ("skill", "procedure", "preference", "contact") else "temporary",
            )
            db.add(capsule)

        await db.commit()

    await engine.dispose()

    return {
        "entity_key": entity_key,
        "username": username,
        "display_name": user_data["display_name"],
        "port": entity["port"],
        "capsule_count": len(capsules),
        "did": agent_did,
    }


async def seed_all():
    """Generate all 19 pod databases."""
    print("\n=== TrustMesh Multi-Pod Seeder ===\n")

    # Clean and create data directory
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True)

    results = []
    for entity_key in POD_ENTITIES:
        db_path = DATA_DIR / f"{entity_key}.db"
        result = await seed_pod(entity_key, str(db_path))
        results.append(result)
        print(f"  Pod {result['port']:5d}  {result['display_name']:<35s}  {result['capsule_count']} capsules  DID: {result['did'][:30]}...")

    print(f"\n=== Generated {len(results)} pod databases in {DATA_DIR} ===")
    print(f"    Total capsules: {sum(r['capsule_count'] for r in results)}\n")

    # Write manifest for launcher script
    manifest = {
        entity_key: {
            "port": POD_ENTITIES[entity_key]["port"],
            "username": result["username"],
            "display_name": result["display_name"],
            "db_path": f"data/pods/{entity_key}.db",
            "type": POD_ENTITIES[entity_key]["type"],
        }
        for entity_key, result in zip(POD_ENTITIES, results)
    }
    manifest_path = DATA_DIR / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"    Manifest: {manifest_path}\n")


if __name__ == "__main__":
    asyncio.run(seed_all())
