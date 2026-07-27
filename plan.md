# 🏥 AI Clinical Workflow Engine
### An Open-Source LangChain + LangGraph Healthcare Project

## Overview

This project is an open-source healthcare AI workflow engine demonstrating production-grade AI orchestration using **LangChain**, **LangGraph**, **FHIR**, and **RAG**.

Unlike a typical RAG chatbot, this project focuses on **workflow orchestration**, **tool calling**, **state management**, **human-in-the-loop approval**, and **observability**.

The entire project is built using open healthcare standards and synthetic patient data so anyone can run it locally.

---

# Goals

## Primary Goals

- Learn LangChain beyond basic RAG
- Learn LangGraph workflows
- Learn tool calling
- Learn state management
- Learn conditional routing
- Learn human approval workflows
- Learn structured outputs
- Learn healthcare standards (FHIR)
- Build an impressive open-source portfolio project

---

# High-Level Architecture

```text
                      React UI
                          │
                          ▼
                    FastAPI / NestJS
                          │
                          ▼
                  LangGraph Workflow
                          │
      ┌──────────┬────────┴────────┬─────────┐
      ▼          ▼                 ▼         ▼
 Intent     FHIR Tools        RAG Tool   Audit Tool
Classifier     │                  │
      │         ▼                  ▼
      │    HAPI FHIR         Vector Database
      │         │                  │
      └─────────┴──────────┬───────┘
                           ▼
                    Response Generator
```

---

# Workflow

```text
        Patient Request
              │
              ▼
      Intent Classification
              │
     ┌────────┼──────────┐
     ▼        ▼          ▼
Appointment Medication Clinical QA
     │        │          │
     └────────┼──────────┘
              ▼
      Retrieve Patient Data (FHIR)
              ▼
     Retrieve Clinical Guidelines (RAG)
              ▼
      Medical Safety Checker
              ▼
        Need Human Review?
          │           │
         Yes         No
          │           │
          ▼           ▼
   Human Approval   Generate Response
          └───────────┘
                ▼
          Audit Logger
```

---

# Tech Stack

## AI

- LangChain
- LangGraph
- LangSmith (optional)
- OpenAI / Claude / Gemini / Ollama

---

## Backend

- FastAPI (recommended)
- or NestJS

---

## Frontend

- React
- Vite
- TailwindCSS
- React Flow (graph visualization)

---

## Database

- PostgreSQL
- SQLite (development)

---

## Vector Database

- Qdrant (recommended)
- Chroma

---

## Healthcare

- HAPI FHIR Server
- Synthea
- SMART on FHIR (future)

---

## Storage

- Local filesystem
- Docker volumes

---

# Resources Needed

## Patient Data

### Synthea

Generate synthetic patients.

Contains

- Patients
- Encounters
- Conditions
- Allergies
- Medications
- Procedures
- Observations
- Lab Results

---

## FHIR Server

### HAPI FHIR

Run locally using Docker.

Will act as the backend healthcare server.

---

## Clinical Guidelines

Use public PDFs from

- CDC
- WHO
- NICE
- ADA

Used for RAG.

---

# Folder Structure

```text
healthcare-agent/

├── frontend/
│
├── backend/
│
├── langgraph/
│   ├── graph.py
│   ├── state.py
│   ├── router.py
│   ├── nodes/
│   └── edges/
│
├── tools/
│   ├── patient.py
│   ├── medication.py
│   ├── appointment.py
│   ├── guidelines.py
│   ├── audit.py
│   └── safety.py
│
├── rag/
│
├── prompts/
│
├── data/
│
├── tests/
│
├── docker/
│
└── README.md
```

---

# LangGraph State

```python
WorkflowState

- user_query
- intent
- patient_id
- patient_data
- retrieved_guidelines
- safety_result
- requires_human_review
- final_response
- audit_log
```

---

# LangGraph Nodes

## Intent Classifier

Responsible for classifying requests into:

- Appointment
- Medication
- Clinical QA
- Unknown

---

## Appointment Agent

Handles appointment-related workflows.

Possible tools

- search_provider
- search_slots
- create_appointment

---

## Medication Agent

Retrieves

- Active medications
- Dosages
- Medication history

---

## Clinical QA Agent

Answers healthcare questions using

- Patient data
- Clinical guidelines

---

## Retrieve Patient Data

FHIR Tools

- Patient
- Observation
- Encounter
- MedicationRequest
- AllergyIntolerance
- Condition

---

## Retrieve Guidelines

Uses

- Vector search
- Embeddings
- RAG

---

## Medical Safety Checker

Checks for

- Drug interactions
- Missing allergies
- Conflicting recommendations
- Low confidence

---

## Human Approval Node

If confidence is low

↓

Pause graph

↓

Wait for approval

↓

Resume

---

## Response Generator

Produces

- Final answer
- Sources
- Citations

---

## Audit Logger

Stores

- Timestamp
- User query
- Patient ID
- Tools called
- Guideline citations
- Token usage
- Model
- Final response

---

# LangChain Tools

Planned tools

- search_patient()
- search_conditions()
- search_medications()
- search_observations()
- search_appointments()
- create_appointment()
- retrieve_guidelines()
- medical_safety_check()
- create_audit_log()

---

# RAG Pipeline

```text
PDF

↓

Document Loader

↓

Text Splitter

↓

Embeddings

↓

Vector Database

↓

Retriever

↓

LLM
```

---

# Milestones

## Phase 1

- Repository setup
- Docker
- FastAPI
- React
- LangGraph setup

Estimated: 2–3 days

---

## Phase 2

- HAPI FHIR
- Import Synthea data
- Build FHIR tools

Estimated: 3–4 days

---

## Phase 3

- Build RAG pipeline
- Load clinical guidelines
- Connect vector DB

Estimated: 3 days

---

## Phase 4

- Build LangGraph workflow
- Conditional routing
- State management

Estimated: 5–7 days

---

## Phase 5

- Medical safety node
- Human approval
- Interrupt/resume

Estimated: 3 days

---

## Phase 6

- Audit logging
- Observability
- LangSmith

Estimated: 2 days

---

## Phase 7

- Frontend
- Streaming
- Workflow visualization

Estimated: 5 days

---

## Phase 8

- Testing
- Documentation
- Docker Compose
- GitHub release

Estimated: 3 days

---

# Stretch Goals

## Graph Visualization

Display the LangGraph execution in real time.

---

## Workflow Replay

Replay any previous execution.

Inspect

- Node execution
- Tool outputs
- State transitions
- Timing
- Errors

---

## Multi-Agent Workflow

Replace the intent router with specialized agents.

Examples

- Appointment Agent
- Medication Agent
- Clinical QA Agent
- Safety Agent

---

## Conversation Memory

Persist conversation history using LangGraph memory.

---

## SMART on FHIR Login

Allow authentication using SMART on FHIR.

---

## Model Switching

Support

- OpenAI
- Claude
- Gemini
- Ollama

without changing workflow logic.

---

# Testing Strategy

Unit Tests

- Every tool
- Every node
- Every prompt

Integration Tests

- Graph execution
- FHIR server
- Vector DB
- RAG pipeline

End-to-End Tests

- Complete patient workflows
- Human approval
- Error handling

---

# Future Ideas

- Multi-patient workflow
- Insurance authorization agent
- Clinical coding assistant
- Voice scribe integration
- HL7 message support
- FHIR subscriptions
- CDS Hooks integration
- MCP server support
- Multi-hospital configuration

---

# Learning Outcomes

By completing this project, I should have hands-on experience with:

- LangChain LCEL
- LangChain Tools
- Structured Outputs
- LangGraph StateGraph
- Conditional Edges
- Parallel Execution
- Checkpoints
- Interrupts
- Human-in-the-loop workflows
- RAG
- FHIR APIs
- Synthetic healthcare data
- Vector databases
- AI observability
- Production AI architecture

---

# Definition of Done

- Open-source and fully documented
- One-command local setup with Docker Compose
- Uses only synthetic healthcare data
- Demonstrates LangGraph orchestration
- Includes RAG over clinical guidelines
- Integrates with a local FHIR server
- Supports human approval checkpoints
- Provides audit logging and execution tracing
- Includes automated tests and CI
- Easy for others to clone, run, and extend