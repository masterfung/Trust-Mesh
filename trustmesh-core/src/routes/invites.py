"""Network invite routes — email invitations for cold start."""

import html
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.database import get_db
from src.models import Network, NetworkInvite, NetworkMembership, Notification, User, new_uuid, utcnow

router = APIRouter(prefix="/api", tags=["invites"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3050")


class InviteRequest(BaseModel):
    email: str = ""  # Optional — link-based invites don't need email
    message: str = ""


class InviteResponse(BaseModel):
    id: str
    email: str
    token: str
    status: str
    network_name: str


@router.post("/networks/{network_id}/invite", response_model=InviteResponse)
async def send_invite(
    network_id: str,
    req: InviteRequest,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """Send an email invite to join a network."""
    network = await db.get(Network, network_id)
    if not network:
        raise HTTPException(404, "Network not found")
    if network.owner_id != auth_user_id:
        raise HTTPException(403, "Only the network owner can invite members")

    # Generate a secure token
    token = secrets.token_urlsafe(32)

    invite = NetworkInvite(
        network_id=network_id,
        invited_by=network.owner_id,
        email=req.email,
        token=token,
    )
    db.add(invite)
    await db.flush()

    # Try to send email via Resend
    invite_url = f"{FRONTEND_URL}/invite/{token}"
    email_sent = False

    resend_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM_EMAIL", "TrustMesh <onboarding@resend.dev>")

    if resend_key:
        try:
            import resend
            resend.api_key = resend_key

            # Get inviter name
            inviter = await db.get(User, network.owner_id)
            inviter_name = inviter.display_name if inviter else "Someone"

            inviter_name_safe = html.escape(inviter_name)
            network_name_safe = html.escape(network.name)
            invite_url_safe = html.escape(invite_url)
            message_safe = html.escape(req.message or "")

            resend.Emails.send({
                "from": from_email,
                "to": [req.email],
                "subject": f"{inviter_name_safe} invited you to join {network_name_safe} on TrustMesh",
                "html": f"""
                <div style="font-family: system-ui, sans-serif; max-width: 500px; margin: 0 auto; padding: 40px 20px;">
                    <h1 style="color: #7c5cfc; margin-bottom: 4px;">TrustMesh</h1>
                    <p style="color: #888; margin-top: 0;">Trust-Aware Knowledge Sharing</p>
                    <hr style="border: 1px solid #eee; margin: 24px 0;">
                    <p><strong>{inviter_name_safe}</strong> invited you to join the <strong>{network_name_safe}</strong> network.</p>
                    {f'<p style="color: #666; font-style: italic;">"{message_safe}"</p>' if message_safe else ''}
                    <p>TrustMesh is where your personal AI agent holds your knowledge and shares it with the right people — powered by trust networks and encrypted vaults.</p>
                    <a href="{invite_url_safe}" style="display: inline-block; background: #7c5cfc; color: white; padding: 12px 32px; border-radius: 12px; text-decoration: none; font-weight: 600; margin: 16px 0;">
                        Accept Invite
                    </a>
                    <p style="color: #888; font-size: 13px;">Or copy this link: {invite_url_safe}</p>
                </div>
                """,
            })
            email_sent = True
        except Exception as e:
            # Email failed but invite token still created
            pass

    await db.commit()

    return InviteResponse(
        id=invite.id,
        email=req.email,
        token=token,
        status="sent" if email_sent else "created",
        network_name=network.name,
    )


@router.get("/invite/{token}")
async def validate_invite(token: str, db: AsyncSession = Depends(get_db)):
    """Validate an invite token and return network info."""
    result = await db.execute(
        select(NetworkInvite).where(NetworkInvite.token == token, NetworkInvite.status == "pending")
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(404, "Invalid or expired invite")

    network = await db.get(Network, invite.network_id)
    inviter = await db.get(User, invite.invited_by)

    return {
        "valid": True,
        "network_id": invite.network_id,
        "network_name": network.name if network else "Unknown",
        "invited_by": inviter.display_name if inviter else "Unknown",
        "email": invite.email,
    }


@router.post("/invite/{token}/accept")
async def accept_invite(
    token: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Accept an invite — adds user to the network."""
    result = await db.execute(
        select(NetworkInvite).where(NetworkInvite.token == token, NetworkInvite.status == "pending")
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(404, "Invalid or expired invite")

    # Check user exists
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    # Check not already a member
    existing = await db.execute(
        select(NetworkMembership).where(
            NetworkMembership.network_id == invite.network_id,
            NetworkMembership.user_id == user_id,
        )
    )
    if existing.scalar_one_or_none():
        invite.status = "accepted"
        invite.accepted_at = utcnow()
        await db.commit()
        return {"ok": True, "message": "Already a member"}

    # Add to network
    membership = NetworkMembership(
        network_id=invite.network_id,
        user_id=user_id,
    )
    db.add(membership)

    # Update invite status
    invite.status = "accepted"
    invite.accepted_at = utcnow()

    # Notify the inviter
    network = await db.get(Network, invite.network_id)
    notification = Notification(
        user_id=invite.invited_by,
        notification_type="network_joined",
        title=f"{user.display_name} joined {network.name if network else 'your network'}",
        body=f"{user.display_name} accepted your invitation and joined the network.",
    )
    db.add(notification)

    await db.commit()

    return {"ok": True, "network_id": invite.network_id, "network_name": network.name if network else ""}


@router.get("/networks/{network_id}/invites")
async def list_invites(
    network_id: str,
    db: AsyncSession = Depends(get_db),
    auth_user_id: str = Depends(get_current_user_id),
):
    """List pending invites for a network."""
    network = await db.get(Network, network_id)
    if not network:
        raise HTTPException(404, "Network not found")
    if network.owner_id != auth_user_id:
        raise HTTPException(403, "Only the network owner can view invites")
    result = await db.execute(
        select(NetworkInvite).where(NetworkInvite.network_id == network_id).order_by(NetworkInvite.created_at.desc())
    )
    invites = result.scalars().all()
    return [
        {
            "id": i.id,
            "email": i.email,
            "status": i.status,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in invites
    ]
