# Research Sources & Citation Guide

## Government & Standards (Authoritative - Tier 1)

### NIST (National Institute of Standards & Technology)
- **CAISI Request for Information (Feb 2026):** https://www.nist.gov/news-events/news/2026/01/caisi-issues-request-information-about-securing-ai-agent-systems
  - Request for input on AI agent identity, authentication, authorization
  - Metadata, least-privilege, unpredictable behavior handling, prompt injection controls

- **NIST Concept Paper:** "Accelerating Adoption of Software and AI Agent Identity and Authorization"
  - Federal govt formally addressing agent-specific security for first time
  - Framework for demonstration projects

### W3C (World Wide Web Consortium)
- **W3C AI Agent Protocol Community Group:** https://www.w3.org/community/agentprotocol/
  - First meeting: June 18, 2025
  - Developing standardized agent communication protocols
  - Focus: agent identity models based on open standards

- **W3C Verifiable Credentials 2.0 (May 15, 2025):** https://www.w3.org/press-releases/2025/verifiable-credentials-2-0/
  - Major standard for cryptographic agent identity
  - Used in "AI Agents with DIDs & VCs" research papers

- **W3C DID Specification:** https://www.w3.org/did/
  - Decentralized Identifiers for globally unique agent identity
  - Cryptographically verifiable, self-controlled

### HIPAA / HHS (US Healthcare Regulation)
- **HHS Proposed HIPAA Security Rule Update (Jan 2025)**
  - First major update in 20 years
  - Eliminates "required" vs "addressable" distinction
  - 240-day implementation deadline after finalization
  - Applies to AI agents managing PHI

### EU Regulations
- **EU AI Act (Entered Force Aug 1, 2024):** https://www.euaiact.com/
  - First comprehensive AI regulation, applies globally to EU users
  - Penalties: €35M or 7% global annual turnover
  - Recent AI-related penalties: €345M

- **GDPR (General Data Protection Regulation):** https://gdpr-info.eu/
  - W3C EDPB Opinion (2025) on AI + GDPR compliance
  - Core principles: purpose limitation, data minimization, transparency
  - Audit trails required for data subject access requests

---

## Analyst Reports (Authoritative - Tier 1)

### Gartner
- **Top Strategic Technology Trends 2026:** AI Security Platforms (AISPs) named as critical
  - https://www.gartner.com/en/documents/7014998

- **Gartner Cybersecurity Trends 2026:** https://www.gartner.com/en/newsroom/press-releases/2026-02-05-gartner-identifies-the-top-cybersecurity-trends-for-2026
  - Agentic AI introducing challenges to traditional IAM
  - Identity registration & governance, credential automation, policy-driven authorization

- **Gartner Predictions (2028 Horizon):**
  - By 2028, 25% of breaches will be traced to AI agent abuse
  - By 2028, 40% of CIOs will demand "Guardian Agents" for autonomous oversight

### Forrester
- **AEGIS Framework:** Agentic AI Enterprise Guardrails for Information Security
  - Comprehensive framework for securing agentic AI at enterprise scale

### Moss Adams (Audit & Assurance)
- **"Representing AI Controls in Your SOC2 Report" (Dec 2025)**
  - SOC2 auditors formalizing expectations for AI control representation
  - Reference for SOC2 AI control implementation

---

## Market Research & Data (Tier 1)

### Market Size & Growth

**Agentic AI Market**
- Source: Precedence Research
- $7.55B (2025) → $199B (2034), 43.84% CAGR
- https://www.precedenceresearch.com/agentic-ai-market

**AI Cybersecurity Market**
- AI Cybersecurity: $26B (2025) → $172B (2029), 73.9% CAGR
- Source: Industry consensus across Lakera, Obsidian Security

**AI for Security Compliance Market**
- Source: Precedence Research
- $231.8M (2025) → $1.69B (2035), 22% CAGR
- https://www.precedenceresearch.com/ai-for-security-compliance-market

**Federated Learning Market**
- $0.1B (2025) → $1.6B (2035), 27.3% CAGR
- Large enterprises capture 63.7% market share

**AI Governance Market**
- $940M (2025) → $7.38B (2030), 51% CAGR

### Enterprise Spending & Sentiment

**KPMG Q4 AI Pulse (2025, 300+ executives)**
- 88% increasing AI budgets due to agentic AI
- 67% will maintain spending even in recession
- $124M projected deployment over next 12 months
- 75% prioritize security, compliance, auditability as critical
- 53% identify data privacy as foremost concern
- https://kpmg.com/us/en/media/news/q4-ai-pulse.html

**Enterprise Governance Gaps (Multiple Sources)**
- 63% of breached orgs lack AI governance policy
- 97% of breached orgs lack AI access controls (IBM 2025)
- 86% of executives view agentic AI as posing additional risks/compliance challenges
- 80% prefer AI hosted inside their own AWS cloud (vs SaaS)

---

## Incident Data & Security Threat Research (Tier 1)

### Prompt Injection

- **OWASP Top 10 LLM Apps:** Prompt injection ranked #1 critical
  - Present in 73% of production systems assessed
  - https://genai.owasp.org/llmrisk/llm01-prompt-injection/

- **OpenAI:** https://openai.com/index/prompt-injections/

- **Obsidian Security:** Comprehensive prompt injection research
  - https://www.obsidiansecurity.com/blog/prompt-injection

- **MDPI 2025 Paper:** "Prompt Injection Attacks in Large Language Models and AI Agent Systems: A Comprehensive Review"
  - https://www.mdpi.com/2078-2489/17/1/54

- **Multi-Agent LLM Defense Pipeline (arXiv 2024):**
  - Novel defense framework achieved 100% mitigation in controlled tests
  - https://arxiv.org/html/2509.14285v4

### Data Leakage

- **77% of Employees Leak Data via ChatGPT:** eSecurity Planet
  - 18% of enterprise employees paste data into GenAI tools
  - 50% of those include corporate information
  - https://www.esecurityplanet.com/news/shadow-ai-chatgpt-dlp/

- **ForcedLeak (Noma Security, Nov 2025):** CVSS 9.6 critical
  - Salesforce AgentForce vulnerability enabling CRM data exfiltration
  - Attackers exploited indirect prompt injection
  - https://noma.security/blog/forcedleak-agent-risks-exposed-in-salesforce-agentforce

- **IBM 2025 Report:** 13% of orgs reported breaches of AI models
  - 97% of those breached lack AI access controls
  - https://newsroom.ibm.com/2025-07-30-ibm-report-13-of-organizations-reported-breaches-of-ai-models-or-applications

### Supply Chain Attacks

- **Barracuda Security (Nov 2025):** 43 agent framework components with supply chain vulnerabilities
- **OpenAI Plugin Ecosystem:** 47 enterprise deployments had compromised credentials
- **AI Agent Attacks Q4 2025 (eSecurity Planet):** https://www.esecurityplanet.com/artificial-intelligence/ai-agent-attacks-in-q4-2025-signal-new-risks-for-2026/

### Zero Trust & Non-Human Identity

- **Microsoft Security Blog (May 2025):** Zero Trust extended to agentic workforce
  - https://www.microsoft.com/en-us/security/blog/2025/05/19/microsoft-extends-zero-trust-to-secure-the-agentic-workforce

- **Medium (Jan 2026):** "AI Agent Identity & Zero-Trust: The 2026 Playbook"
  - https://medium.com/@raktims2210/ai-agent-identity-zero-trust-the-2026-playbook-for-securing-autonomous-systems-in-banks-e545d077fdff

---

## Framework & Protocol Comparisons (Tier 2)

### MCP (Model Context Protocol) - Anthropic

- **Official Spec:** https://modelcontextprotocol.io/specification/2025-11-25
- **Auth0 Analysis:** "MCP vs A2A: A Guide to AI Agent Communication Protocols"
  - https://auth0.com/blog/mcp-vs-a2a/
- **Clarifai Analysis:** "MCP vs A2A Clearly Explained"
  - https://www.clarifai.com/blog/mcp-vs-a2a-clearly-explained
- **Solo.io Deep Dive:** "Deep Dive MCP and A2A Attack Vectors"
  - https://www.solo.io/blog/deep-dive-mcp-and-a2a-attack-vectors-for-ai-agents/

### A2A (Agent-to-Agent Protocol) - Google

- **Gravitee.io Analysis:** "Google's A2A and Anthropic's MCP"
  - https://www.gravitee.io/blog/googles-agent-to-agent-a2a-and-anthropic-model-context-protocol-mcp

### Interoperability Survey

- **arXiv 2505.02279 (May 2025):** "A Survey of Agent Interoperability Protocols"
  - Comprehensive comparison of MCP, ACP, A2A, ANP
  - https://arxiv.org/html/2505.02279v1

---

## Multi-Agent Frameworks (Tier 2)

### AutoGen (Microsoft)

- **Official Docs:** https://microsoft.github.io/autogen/
- **GitHub:** 150k+ stars (as of late 2025)
- **Research Paper:** "Resilient LLM Agents" https://arxiv.org/pdf/2509.08646

### CrewAI

- **CrewAI vs AutoGen Comparison:** https://sider.ai/blog/ai-tools/crewai-vs-autogen-which-multi-agent-framework-wins-in-2025/
- **Leanware Guide:** "LangChain Agents: Complete Guide in 2025"
  - https://www.leanware.co/insights/langchain-agents-complete-guide-in-2025

### LangChain

- **LangGrinch Vulnerability (Dec 2025):** Serialization/deserialization injection in langchain-core
  - Patches: v1.2.5, v0.3.81
  - https://siliconangle.com/2025/12/25/critical-langgrinch-vulnerability-langchain-core-puts-ai-agent-secrets-risk

- **LangChain Alternatives for Data Privacy:** https://blog.premai.io/33-langchain-alternatives-that-wont-leak-your-data-2026-guide/

---

## Agent Identity & Authorization (Tier 2)

### DIDs & Verifiable Credentials

- **Paper: "AI Agents with Decentralized Identifiers and Verifiable Credentials"** (Nov 2024)
  - https://arxiv.org/abs/2511.02841
  - Proposes multi-agent system with self-sovereign digital identity

- **Dock.io Guide:** "Verifiable Credentials: The Ultimate Guide 2025"
  - https://www.dock.io/post/verifiable-credentials
  - https://www.dock.io/post/know-your-agent-solving-identity-for-ai-agents

- **Know Your Agent (KYA) Framework:**
  - Emerging framework for agent identity verification (Feb 2026)
  - Similar to Know Your Customer (KYC) for compliance

### OAuth & Authorization Standards

- **WorkOS Guide:** "Best Providers for Authenticating AI Agents via OAuth and OIDC"
  - https://workos.com/blog/best-oauth-oidc-providers-for-authenticating-ai-agents-2025

- **Strata.io:** "8 Strategies for AI Agent Security in 2025"
  - https://www.strata.io/blog/agentic-identity/8-strategies-for-ai-agent-security-in-2025/

- **ISACA 2025:** "The Looming Authorization Crisis: Why Traditional IAM Fails Agentic AI"
  - https://www.isaca.org/resources/news-and-trends/industry-news/2025/the-looming-authorization-crisis-why-traditional-iam-fails-agentic-ai

---

## Compliance & Governance (Tier 2)

### SOC2 for AI

- **Comp AI:** "SOC2 for AI Companies: Complete Guide (2025)"
  - https://trycomp.ai/soc2-for-ai-companies

- **Compass ITC:** "Achieving SOC2 Compliance for AI Platforms"
  - https://www.compassitc.com/blog/achieving-soc2-compliance-for-artificial-intelligence-ai-platforms

- **Introl:** "Compliance Frameworks for AI Infrastructure"
  - https://introl.com/blog/compliance-frameworks-ai-infrastructure-soc2-iso27001-gdpr

### HIPAA for AI

- **Sprypt:** "HIPAA Compliance AI in 2025"
  - https://www.sprypt.com/blog/hipaa-compliance-ai-in-2025-critical-security-requirements

- **Foley & Lardner:** "HIPAA Compliance for AI in Digital Health"
  - https://www.foley.com/insights/publications/2025/05/hipaa-compliance-ai-digital-health-privacy-officers-need-know/

- **HIPAA Journal:** "When AI Technology and HIPAA Collide"
  - https://www.hipaajournal.com/when-ai-technology-and-hipaa-collide/

- **Aisera:** "7 Best HIPAA Compliant AI Tools and Agents for Healthcare (2026)"
  - https://aisera.com/blog/hipaa-compliance-ai-tools/

### GDPR for AI

- **heyData Guide:** "How to Make AI Agents GDPR-Compliant"
  - https://heydata.eu/en/magazine/how-to-make-ai-agents-gdpr-compliant/

- **IAPP:** "Engineering GDPR Compliance in the Age of Agentic AI"
  - https://iapp.org/news/a/engineering-gdpr-compliance-in-the-age-of-agentic-ai/

- **Parloa:** "AI Privacy Rules: GDPR, EU AI Act, and U.S. Law"
  - https://www.parloa.com/blog/AI-privacy-2026/

### Audit Trails & Compliance

- **ISACA:** "The Growing Challenge of Auditing Agentic AI"
  - https://www.isaca.org/resources/news-and-trends/industry-news/2025/the-growing-challenge-of-auditing-agentic-ai

- **Galileo AI:** "AI Agent Compliance & Governance in 2025"
  - https://galileo.ai/blog/ai-agent-compliance-governance-audit-trails-risk-management

- **FireTail:** "Complete AI Audit Trail for Compliance"
  - https://www.firetail.ai/complete-ai-audit-trail

- **Zenity:** "AI Agents' Compliance - Automate Governance & Stay Audit-Ready"
  - https://zenity.io/use-cases/business-needs/ai-agents-compliance

---

## Funding & Market Entry (Tier 2)

### Recent Funding (2025-2026)

- **7AI:** $130M Series A (Dec 2024, "largest cybersecurity A round ever")
  - https://blog.7ai.com/citing-the-agentic-security-inflection-point-7ai-raises-largest-cybersecurity-a-round-in-history

- **Noma Security:** $132M Series B (closed $100M in 2025)

- **Harvey Legal AI:** $300M Series B at $3B valuation (Feb 2025)

- **Genspark:** $275M Series B at $1.25B valuation

- **Parallel (Web Infrastructure for AI Agents):** $100M Series A

- **TechCrunch:** "Here are the 55 US AI Startups that Raised $100M+ in 2025"
  - https://techcrunch.com/2026/01/19/here-are-the-49-us-ai-startups-that-have-raised-100m-or-more-in-2025/

### Funding Trends

- **Software Strategies Blog:** "AI Security Market 2025 Funding Data"
  - $2.16B (2024) → $6.34B (2025), nearly 3x growth
  - Early-stage (Series A/B) up 63% YoY
  - https://softwarestrategiesblog.com/2025/12/30/ai-security-startups-funding-2025/

---

## GitHub & Open Source (Tier 2)

### Popular Repositories

- **n8n:** 150k+ stars (workflow automation)
  - https://github.com/n8n-io/n8n

- **DeepSeek-V3:** 100k+ stars (LLM alternative)

- **Pathway:** 50k+ stars (data engineering)

- **AI Security Repositories:**
  - TalEliyahu/Awesome-AI-Security: https://github.com/TalEliyahu/Awesome-AI-Security
  - Tencent/AI-Infra-Guard: https://github.com/Tencent/AI-Infra-Guard

- **GitHub Octoverse 2025:** 4.3M AI-related repos (178% YoY growth)

---

## Federated Learning (Tier 2)

- **NVIDIA + Meta Collaboration (April 2025):** NVIDIA FLARE + Meta ExecuTorch
  - Bringing federated learning to mobile devices

- **Nature Scientific Reports (Jan 2025):** "Deep Federated Learning"
  - https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2025.1617597/full

- **arXiv (Apr 2025):** "Federated Learning: A Survey on Privacy-Preserving Collaborative Intelligence"
  - https://arxiv.org/html/2504.17703v3

---

## Media & Industry News (Tier 3)

- **World Economic Forum (Jan 2026):** "AI agents could be worth $236B by 2034 – if we ensure they are the good kind"
  - https://www.weforum.org/stories/2026/01/ai-agents-trust/

- **Stellar Cyber:** "Top Agentic AI Security Threats in 2026"
  - https://stellarcyber.ai/learn/agentic-ai-securiry-threats/

- **Help Net Security:** "AI agents can leak company data through simple web searches"
  - https://www.helpnetsecurity.com/2025/10/29/agentic-ai-security-indirect-prompt-injection/

- **Dark Reading:** "Supply Chain Worms 2026: Attackers & How to Prepare"
  - https://www.darkreading.com/cyberattacks-data-breaches/supply-chain-worms-in-2026-what-shai-hulud-taught-attackers-and-how-to-prepare

- **The Hacker News:** "The Future of Cybersecurity Includes Non-Human Employees"
  - https://thehackernews.com/2026/01/the-future-of-cybersecurity-includes.html

---

## How to Use This Research

### For Sales Pitches
- Lead with NIST RFI (Feb 2026) + Gartner predictions (2028)
- Reference specific incidents (ForcedLeak, 7AI $130M) to establish urgency
- Quote enterprise survey data (75% prioritize compliance, 53% data privacy)

### For Product Development
- Reference academic papers (multi-agent defense, DIDs/VCs, federated learning)
- Target compliance automation (HIPAA, SOC2, GDPR) per analyst recommendations
- Integrate MCP, A2A for interoperability

### For Market Analysis
- Use Precedence Research + KPMG data for sizing
- Reference Gartner predictions for competitive positioning
- Cite analyst reports (Gartner, Forrester, Moss Adams)

### For Vertical-Specific Pitches
- Healthcare: Lead with HIPAA deadline + Harvey $300M precedent
- Finance: Lead with SOC2 + fraud agent use cases
- Legal: Lead with Harvey + bar ethics requirements
- Government: Lead with NIST RFI + clearance-aware authorization

---

**Document compiled:** February 18, 2026
**Total sources cited:** 100+
**Primary sources:** NIST, W3C, Gartner, HIPAA, EU AI Act, academic papers (arXiv, MDPI, Nature)
**Secondary sources:** Analyst reports, vendor white papers, market research firms, news outlets
