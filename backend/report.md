# Task 3 Automation Workflow: Slack-to-Salesforce Lead Intake Automation

## 1. Workflow Architecture Overview

### Business Outcome Alignment
This automation directly addresses the business need to reduce manual data entry effort by sales teams, improve CRM data accuracy, and accelerate lead response times. The workflow eliminates 2-3 minutes of manual work per lead while ensuring 100% data consistency between communication channels and CRM records.

### System Components & Flow Logic

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│   Slack Workspace │────▶│   Middleware Layer │────▶│   Salesforce Instance │────▶│   Monitoring &   │
│   (Trigger Source)│     │   (Orchestration)  │     │   (CRM Destination)   │     │   Alerting System │
└─────────────────┘     └─────────────────┘     └─────────────────────┘     └─────────────────┘
         │                         │                         │                         │
         │ 1. Message Posted      │ 2. Validate & Enrich    │ 3. Create/Update Lead   │ 4. Log & Monitor
         │    in #sales-leads      │    Lead Data            │    Record               │    Success/Failure
         ▼                         ▼                         ▼                         ▼
```

**Architectural Decisions:**
- **Middleware Approach**: A dedicated orchestration layer (not direct Slack→Salesforce integration) provides resilience, data transformation, and audit capabilities
- **Event-Driven Design**: Asynchronous processing prevents blocking Slack users during Salesforce operations
- **Idempotent Operations**: Each lead processed exactly once, even with retries
- **Decoupled Components**: Each system interacts only with the middleware, simplifying maintenance

### Technology Stack
| Component | Technology Choice | Rationale |
|-----------|-------------------|-----------|
| Trigger Detection | Slack Events API (message.posted) | Real-time, scalable, official API |
| Middleware Runtime | AWS Lambda (Python 3.12) | Serverless, cost-effective, auto-scaling |
| Data Transformation | Custom Python service | Full control over mapping logic |
| Queue/Retry Mechanism | Amazon SQS with DLQ | Guaranteed delivery, retry management |
| Monitoring | Datadog + CloudWatch | Comprehensive observability |
| Secrets Management | AWS Secrets Manager | Secure credential storage |
| Audit Trail | Amazon DynamoDB | Immutable transaction logging |

## 2. Trigger Definition

### Primary Trigger Event
**Slack Event**: `message.posted` in channel `#sales-leads` with specific metadata criteria.

**Trigger Conditions (ALL must be true):**
1. **Channel**: Message posted in `#sales-leads` (channel ID: `C1234567890`)
2. **Message Pattern**: Contains keyword "lead:" or "prospect:" in first 50 characters
3. **User Role**: Posted by users in `sales-team` or `account-executive` user groups
4. **Message Type**: Must be a user message (not bot message, file upload, or thread reply)
5. **Time Window**: Business hours only (8 AM - 6 PM local time, Monday-Friday)

**Trigger Payload Example:**
```json
{
  "token": "verification_token",
  "team_id": "T1234567890",
  "api_app_id": "A1234567890",
  "event": {
    "type": "message",
    "channel": "C1234567890",
    "user": "U1234567890",
    "text": "lead: Acme Corp - John Doe - john@acme.com - Interested in Enterprise Plan",
    "ts": "1625097600.123456",
    "thread_ts": null,
    "channel_type": "channel"
  },
  "type": "event_callback",
  "event_id": "Ev1234567890",
  "event_time": 1625097600
}
```

### Secondary Triggers (Fallback Mechanisms)
1. **Scheduled Polling**: Hourly check for missed messages (cron: `0 * * * *`)
2. **Manual Override**: REST API endpoint for manual lead submission
3. **Email Bridge**: Forwarded emails to Slack channel also processed

## 3. API Integration Details

### Data Flow Sequence

**Step 1: Slack Event Reception**
- Slack Events API → AWS API Gateway endpoint
- Verification of Slack signing secret
- Immediate 200 OK response to Slack (within 3 seconds)
- Event payload enqueued to SQS for async processing

**Step 2: Message Parsing & Validation**
- Lambda function processes SQS message
- Extracts lead information using regex patterns
- Validates required fields (company, contact, email)
- Enriches data with:
  - Lead source: "Slack Channel #sales-leads"
  - Assigned sales rep (based on Slack user mapping)
  - Geographic data (from email domain/IP lookup)

**Step 3: Salesforce Integration**
- OAuth 2.0 JWT Bearer Flow for authentication
- Salesforce REST API (v55.0) for lead operations
- Bulk API for high-volume periods (>10 leads/hour)

### Field Mapping Specification

| Slack Message Component | Salesforce Field | Transformation Logic | Validation Rule |
|-------------------------|------------------|----------------------|-----------------|
| Company name (after "lead:") | `Company` | Extract first 80 chars | Required, max 80 chars |
| Contact person | `FirstName` + `LastName` | Split by space, first word = FirstName, rest = LastName | Required, min 2 chars |
| Email address | `Email` | Extract via regex `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | RFC 5322 compliant |
| Message content | `Description` | Full message text minus parsed components | Max 32,000 chars |
| Slack timestamp | `LeadSource` + custom field | `LeadSource = "Slack"`, `Slack_Message_TS__c` = timestamp | ISO 8601 format |
| Slack user ID | `OwnerId` | Map to Salesforce User ID via lookup table | Must exist in SFDC |
| Product interest keywords | `Product_Interest__c` | Match against product catalog | Predefined picklist values |
| Urgency indicators | `Rating` | "Hot" if contains "urgent", "ASAP", "immediate" | Default: "Warm" |

**Example Transformation:**
```
Slack Input: "lead: TechStart Inc - Sarah Chen - sarah@techstart.io - Needs demo of Premium tier ASAP"

Output Salesforce Fields:
- Company: "TechStart Inc"
- FirstName: "Sarah"
- LastName: "Chen"
- Email: "sarah@techstart.io"
- Description: "Needs demo of Premium tier ASAP"
- LeadSource: "Slack"
- Rating: "Hot"
- Product_Interest__c: "Premium"
- Status: "New"
```

### API Rate Limit Management
- Salesforce: 15,000 API calls per 24 hours (shared limit)
- Slack: 1,000 events per minute (Tier 3 workspace)
- [CALC] Maximum sustainable throughput:
  - Peak: 100 leads/hour × 3 API calls/lead = 300 calls/hour
  - Daily: 8 hours × 100 leads/hour = 800 leads/day × 3 = 2,400 calls/day
  - Safety buffer: 15,000 / 2,400 = 6.25× headroom available

## 4. Error Handling Mechanism

### Three-Tier Retry Strategy

**Tier 1: Immediate Retry (Transient Errors)**
- Errors: Network timeouts, temporary Salesforce unavailability
- Retry count: 2 immediate retries
- Delay: Exponential backoff starting at 2 seconds
- [CALC] Total wait time: 2s + 4s = 6s maximum

**Tier 2: Delayed Retry (Data Errors)**
- Errors: Validation failures, duplicate detection, field length issues
- Retry count: 3 retries with data correction
- Delay: 5 minutes between attempts
- Action: Attempt automatic correction (trim fields, format normalization)
- [CALC] Total processing window: 3 × 5min = 15min + processing time

**Tier 3: Manual Intervention (Permanent Errors)**
- Errors: Invalid credentials, schema changes, permission errors
- Action: Move to Dead Letter Queue (DLQ)
- Alert: Immediate notification to DevOps team via PagerDuty
- Escalation: After 15 minutes, notify Sales Operations manager

### Monitoring & Alerting Matrix

| Error Type | Detection Method | Alert Threshold | Notification Channel | Escalation Path |
|------------|------------------|-----------------|----------------------|-----------------|
| API Authentication | OAuth token refresh failure | 1 consecutive failure | Slack #system-alerts | DevOps → CTO after 30min |
| Data Validation | >20% rejection rate | 5-minute rolling window | Email + Slack DM | Sales Ops immediate |
| Throughput Degradation | <50% of expected volume | 1-hour period | CloudWatch Alarm | Engineering team |
| End-to-End Latency | >30 seconds P95 | 15-minute average | Datadog Dashboard | SRE on-call |
| Message Loss | DLQ size > 10 | Any time | PagerDuty | Immediate page |

### Recovery Procedures
1. **Partial Outage (Salesforce)**: Queue messages in SQS (7-day retention), resume when available
2. **Partial Outage (Slack)**: Enable polling mode, check last 24 hours of messages
3. **Complete Outage**: Manual CSV import via Salesforce Data Loader with audit trail

## 5. Security & Compliance Notes

### Data Protection Measures

**In Transit:**
- TLS 1.2+ for all API communications
- Slack signing secret verification for all inbound requests
- OAuth 2.0 with JWT tokens for Salesforce authentication
- IP whitelisting for middleware endpoints

**At Rest:**
- Secrets stored in AWS Secrets Manager (automatic rotation every 90 days)
- Message payloads encrypted using AWS KMS (AES-256)
- Audit logs immutable in DynamoDB with 7-year retention
- PII masking in logs (email domains only, no full addresses)

### Compliance Alignment

| Regulation | Requirement | Implementation |
|------------|-------------|----------------|
| GDPR | Right to erasure | Salesforce field `IsDeleted` flag, not physical deletion |
| CCPA | Data access requests | Export capability via Salesforce reporting |
| SOC 2 | Audit trail | Complete transaction logging with user context |
| HIPAA (if applicable) | PHI protection | No medical information in Slack messages policy |
| Internal Policy | Sales data classification | All leads classified as "Confidential - Internal" |

### Access Control Matrix

| Role | Slack Access | Salesforce Access | Middleware Access |
|------|--------------|-------------------|-------------------|
| Sales Representative | Read/Write #sales-leads | Read/Write own leads | None |
| Sales Manager | Read all channels | Read team leads, Write all | Read-only metrics |
| Sales Operations | Read/Write all channels | Read/Write all leads | Configuration access |
| DevOps Engineer | None | None | Full operational access |
| System Account | Bot token only | Integration user only | Execution role only |

### Assumptions Documented
1. **Assumption A1**: Slack workspace is Enterprise Grid with compliance features enabled
2. **Assumption A2**: Salesforce org has API access enabled and available API licenses
3. **Assumption A3**: All sales team members complete data handling training annually
4. **Assumption A4**: No sensitive customer data (SSN, credit cards) will be shared via Slack
5. **Assumption A5**: Company maintains Business Associate Agreement if healthcare clients exist

## 6. Performance Metrics Baseline

### Throughput Calculations

**Expected Volume:**
- Current manual process: ~50 leads/day
- Expected increase with automation: 60% more leads captured
- [CALC] Target volume: 50 × 1.6 = 80 leads/day average
- [CALC] Peak capacity (holiday sales): 80 × 3 = 240 leads/day
- [CALC] Maximum sustainable: 100 leads/hour × 8 hours = 800 leads/day

**System Capacity Design:**
- Lambda concurrency: 100 concurrent executions
- SQS throughput: 3,000 messages/second (standard queue)
- [CALC] Bottleneck analysis: Salesforce API (300 calls/hour) limits to 100 leads/hour
- [CALC] Headroom: 100 / 80 = 25% capacity buffer at target volume

### Latency Service Level Objectives

| Metric | Target | Warning | Critical | Measurement Method |
|--------|--------|---------|----------|-------------------|
| End-to-end processing | ≤ 10 seconds P95 | 10-20 seconds | > 20 seconds | CloudWatch metrics |
| Slack API response | ≤ 3 seconds P99 | 3-5 seconds | > 5 seconds | API Gateway logs |
| Salesforce API call | ≤ 2 seconds P95 | 2-4 seconds | > 4 seconds | Lambda execution logs |
| Queue time | ≤ 1 second P95 | 1-3 seconds | > 3 seconds | SQS CloudWatch |
| Data validation | ≤ 500ms P99 | 500ms-1s | > 1 second | Custom metrics |

**Current Baseline Measurements:**
- Manual process latency: 2-3 minutes per lead (data entry time)
- [CALC] Improvement factor: 180 seconds / 10 seconds = 18× faster
- [CALC] Time savings: 80 leads/day × 2.5 minutes saved = 200 minutes/day = 3.3 hours/day

### Failure Rate Expectations

| Failure Type | Acceptable Rate | Monitoring Threshold | Business Impact |
|--------------|----------------|----------------------|-----------------|
| Total system failure | < 0.1% (99.9% uptime) | > 0.5% for 5 minutes | High - manual fallback |
| Individual lead failure | < 2% of total volume | > 5% for 1 hour | Medium - review required |
| Data corruption | < 0.01% | Any occurrence | Critical - immediate fix |
| SLA violation | < 1% of requests | > 5% for 30 minutes | Medium - performance review |

**Availability Calculation:**
- Component availability: Slack (99.95%), AWS (99.99%), Salesforce (99.9%)
- [CALC] Theoretical maximum: 0.9995 × 0.9999 × 0.999 = 0.9984 = 99.84%
- [CALC] Annual downtime allowance: (1 - 0.9984) × 365 × 24 × 60 = 84 minutes/year

## 7. Deployment Readiness Checklist

### Pre-Deployment Requirements

**Infrastructure (AWS)**
- [ ] AWS Account with appropriate permissions (Dev/Prod separation)
- [ ] VPC configured with NAT Gateway for outbound Salesforce access
- [ ] Lambda functions deployed with 512MB memory, 30s timeout
- [ ] SQS queues created (main and DLQ) with 7-day retention
- [ ] API Gateway endpoint with custom domain and WAF rules
- [ ] CloudWatch alarms configured for all critical metrics
- [ ] IAM roles with least-privilege permissions
- [ ] Secrets Manager entries for Slack and Salesforce credentials
- [ ] DynamoDB table for audit logging with TTL enabled

**Slack Configuration**
- [ ] Slack App created in workspace with appropriate scopes:
  - `channels:history` (read channel messages)
  - `channels:read` (get channel info)
  - `groups:read` (read user groups)
  - `users:read` (get user info)
- [ ] Event subscription enabled for `message.channels`
- [ ] Request URL verified with Slack (API Gateway endpoint)
- [ ] Bot user added to `#sales-leads` channel
- [ ] User group mappings configured (sales-team → Salesforce owners)
- [ ] Testing with restricted channel completed

**Salesforce Configuration**
- [ ] Connected App created with OAuth settings:
  - API Enabled permission
  - JWT Bearer Flow enabled
  - IP restrictions applied
- [ ] Integration user created with profile:
  - "Marketing User" checkbox enabled
  - "API Enabled" permission
  - Lead object permissions (CRUD)
  - Custom field access
- [ ] Lead assignment rules reviewed (avoid conflict with automation)
- [ ] Validation rules updated to allow Slack-originated leads
- [ ] Duplicate rules configured to prevent true duplicates
- [ ] Required fields confirmed (Company, LastName minimum)
- [ ] Web-to-Lead disabled for overlapping capture

**Data Mapping Validation**
- [ ] Test suite executed with 50 sample messages
- [ ] Field mapping confirmed for 100% of test cases
- [ ] Edge cases tested:
  - International characters in company names
  - Multiple email addresses in message
  - Missing required fields
  - Extremely long messages (>1000 chars)
- [ ] Salesforce record inspection shows correct field population
- [ ] Owner assignment logic verified against user mapping table

### Go-Live Sequence

**Phase 1: Dry Run (Week 1)**
1. Deploy to staging environment (identical to production)
2. Configure Slack event to staging endpoint
3. Process 20 real leads with `IsTest__c = true` flag in Salesforce
4. Validate all data flows without affecting production CRM
5. Sales team review of sample output

**Phase 2: Shadow Mode (Week 2)**
1. Deploy to production infrastructure
2. Process all leads but mark as `Status = "Shadow Test"`
3. Manual entry continues in parallel
4. Compare automated vs manual records (100% match required)
5. Performance metrics collection and tuning

**Phase 3: Gradual Cutover (Week 3)**
1. Enable lead creation for 25% of sales team (early adopters)
2. Monitor for 48 hours, address any issues
3. Expand to 50% of team
4. Full rollout to 100% after successful validation
5. Disable manual entry process

**Phase 4: Post-Deployment (Week 4+)**
1. Daily review of failure logs for first 14 days
2. Weekly performance report to stakeholders
3. Monthly optimization based on usage patterns
4. Quarterly security review and credential rotation

### Rollback Plan
1. **Level 1 (Minor Issues)**: Disable Slack event subscription, manual processing resumes
2. **Level 2 (Data Issues)**: Deploy previous Lambda version, maintain queue processing
3. **Level 3 (System Issues)**: Redirect API Gateway