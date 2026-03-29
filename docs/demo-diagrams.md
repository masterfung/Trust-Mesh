# TinyFish Accelerator — TrustMesh Demo Video Diagrams

## Diagram 1: The Problem — Data Silos

A family of three wants to plan a trip to San Sebastián, Spain. Today, each person's preferences are scattered across different apps with no secure way for their AI agents to coordinate. This diagram shows the pain: manual data collection, no encryption, no trust layer.

```mermaid
graph TB
    subgraph Peter["🧑 Peter (Dad)"]
        P_Notes["📝 Apple Notes<br/>Vegetarian<br/>47 Starbucks mugs<br/>31 Hard Rock pins<br/>Loves live music"]
        P_Email["📧 Email<br/>No early mornings<br/>Travel dates"]
    end

    subgraph Molly["👩 Molly (Mom)"]
        M_Text["💬 iMessage Group<br/>Walking tours<br/>Wine preferences<br/>Yoga schedule"]
        M_Notes["📝 Notes App<br/>Food markets<br/>Salsa dancing<br/>Budget limits"]
    end

    subgraph Rose["👵 Grandma Rose"]
        R_Phone["📱 Memory App<br/>Michelin dining<br/>No French/Italian<br/>Opera house<br/>Museum hours"]
        R_Meds["💊 Med Schedule<br/>Lactose intolerant<br/>Mobility: walker<br/>Doctor notes"]
    end

    Molly -->|"Manual texts<br/>& calls"| Peter
    Molly -->|"Manual texts<br/>& calls"| Rose
    Peter -->|"Fragmented"| Rose

    Problem["❌ The Problem:<br/>• No secure bridge between vaults<br/>• Data scattered across apps<br/>• No encryption across pods<br/>• Agents can't coordinate<br/>• Information goes stale"]

    style Peter fill:#ffe6e6
    style Molly fill:#e6f3ff
    style Rose fill:#fff3e6
    style Problem fill:#f0f0f0,stroke:#d00,stroke-width:3px
    style P_Notes fill:#fff
    style P_Email fill:#fff
    style M_Text fill:#fff
    style M_Notes fill:#fff
    style R_Phone fill:#fff
    style R_Meds fill:#fff
```

---

## Diagram 2: The Solution — TrustMesh + TinyFish Architecture

Each family member has their own encrypted pod. Trust networks connect them. Molly's agent orchestrates: it queries Peter's and Rose's pods via federation, browses the web with TinyFish, synthesizes recommendations, and saves the itinerary back to Molly's vault — all securely.

```mermaid
graph TB
    subgraph Network["🤝 Trust Network: 'The Johnsons'"]
        direction LR

        subgraph Peter_Pod["🔐 Peter's Pod :9002"]
            P_Vault["Vault (AES-256-GCM)<br/>Zig Transit Engine"]
            P_Capsules["📦 Capsules:<br/>• Diet: Vegetarian<br/>• Collections<br/>• Availability"]
            P_Agent["🤖 Peter's Agent<br/>responds to queries"]
            P_Vault <--> P_Capsules
            P_Capsules <--> P_Agent
        end

        subgraph Molly_Pod["🔐 Molly's Pod :9001"]
            M_Vault["Vault (AES-256-GCM)<br/>Zig Transit Engine"]
            M_Capsules["📦 Capsules:<br/>• Preferences<br/>• Budget<br/>• Mobility needs"]
            M_Agent["🤖 Molly's Agent<br/>Orchestrator"]
            M_Vault <--> M_Capsules
            M_Capsules <--> M_Agent
        end

        subgraph Rose_Pod["🔐 Rose's Pod :9004"]
            R_Vault["Vault (AES-256-GCM)<br/>Zig Transit Engine"]
            R_Capsules["📦 Capsules:<br/>• Dining standards<br/>• Health data<br/>• Cultural interests"]
            R_Agent["🤖 Rose's Agent<br/>responds to queries"]
            R_Vault <--> R_Capsules
            R_Capsules <--> R_Agent
        end

        M_Agent -->|"query_peer<br/>federation"| P_Agent
        M_Agent -->|"query_peer<br/>federation"| R_Agent
        P_Agent -->|"decrypted<br/>capsules"| M_Agent
        R_Agent -->|"decrypted<br/>capsules"| M_Agent
    end

    TinyFish["🧠 TinyFish Research<br/>Live web search<br/>Michelin Guide<br/>Opera schedules<br/>Museums & tours"]

    M_Agent -->|"browse_web<br/>enrich context"| TinyFish
    TinyFish -->|"fresh data<br/>recommendations"| M_Agent

    Itinerary["📋 San Sebastián Itinerary<br/>✓ Vegetarian restaurants (Peter)<br/>✓ Wine walks (Molly)<br/>✓ Michelin dining (Rose)<br/>✓ Accessible venues<br/>✓ Live music schedule"]

    M_Agent -->|"synthesize &<br/>save to vault"| Itinerary
    Itinerary -->|"shared with<br/>trust network"| Network

    style Network fill:#e6ffe6,stroke:#0a0,stroke-width:2px
    style Peter_Pod fill:#ffe6e6,stroke:#c00
    style Molly_Pod fill:#e6f3ff,stroke:#00c
    style Rose_Pod fill:#fff3e6,stroke:#a80
    style TinyFish fill:#f0e6ff,stroke:#60c,stroke-width:2px
    style Itinerary fill:#e6ffe6,stroke:#0a0,stroke-width:3px
```

---

## Diagram 3: Live Update Flow — Peter Changes Diet

Peter updates his diet on his pod. Molly's agent re-queries via federation and sees the change instantly. No central database — each pod is sovereign.

```mermaid
sequenceDiagram
    participant P as Peter<br/>Pod :9002
    participant M as Molly<br/>Pod :9001

    Note over P: Diet = VEGETARIAN

    P->>P: CLI: vault update<br/>Vegetarian → Pescatarian
    P->>P: Re-encrypt AES-256-GCM

    Note over P: Diet = PESCATARIAN

    M->>P: query_peer via federation<br/>What is Peter's diet now?
    P->>P: Decrypt capsule
    P-->>M: Pescatarian!<br/>Loves sushi, ceviche,<br/>seafood paella

    M->>M: Update trip itinerary<br/>Add seafood restaurants
    M->>M: Save + encrypt + share<br/>with The Johnsons network

    Note over P,M: No central database<br/>Each pod is sovereign
```

---

## Key Architecture Patterns Illustrated

### Diagram 1 Insights
- **Problem**: Data fragmentation across closed apps creates coordination friction
- **Pain Points**: Manual collection, no encryption, no trust layer, stale information

### Diagram 2 Insights
- **Solution**: Each pod is a sovereign encrypted vault (AES-256-GCM, Zig transit engine)
- **Trust Network**: Family members explicitly grant query access via "The Johnsons" network
- **Federation**: `query_peer` allows cross-pod agent communication with decryption only at source
- **TinyFish Integration**: Live web research enriches AI synthesis with fresh data
- **Synthesis**: Orchestrating agent (Molly) combines all data sources into actionable recommendations
- **Ownership**: Itinerary saved back to Molly's vault, shared via trust network

### Diagram 3 Insights
- **Sovereignty**: Peter's data only decrypts on Peter's pod
- **Live Updates**: No re-entry required — agents query live encrypted state
- **No Central DB**: Each pod manages its own capsules; federation is read-only query
- **Freshness**: Updated itinerary automatically reflects new preferences
- **Trust Boundary**: Federation queries respect the trust network's permissions

---

## Demo Narrative

**Opening**: "Today, family trip planning is fragmented. Everyone's preferences live in separate apps."
- *Show Diagram 1: Data silos*

**The Solution**: "TrustMesh puts each person's data in an encrypted pod. Trust networks connect them."
- *Show Diagram 2: Architecture overview*

**Live Demo**: "Watch what happens when Peter changes his diet..."
- *Show Diagram 3: Sequence of updates flowing through the network*

**Closing**: "No central database. No re-entry. Just secure, real-time coordination across trusted pods."
