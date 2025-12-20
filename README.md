<p align="center">
  <img src="assets/tessera.jpg" alt="Tessera" width="300">
</p>

# tessera

Data contract coordination for warehouses.

## The Problem

Data contracts tell you something is wrong. They don't tell you what to do about it.

The Kafka ecosystem solved producer/consumer coordination years ago with schema registries. Warehouses have nothing equivalent. When a producer wants to drop a column, rename a field, or change a type, the workflow is tribal knowledge: Slack threads, Confluence pages, and hope.

## What Tessera Does

Tessera is a coordination layer between data producers and consumers. It tracks:

- **Who owns what**: Explicit ownership of tables, views, and models
- **Who depends on what**: Consumers register their dependencies
- **What's changing**: Producers propose schema changes
- **Who's affected**: Impact analysis before deploy
- **Who's acknowledged**: Breaking changes require consumer sign-off

## Core Concepts

**Asset**: A data object (table, view, dbt model) with an owner.

**Contract**: A versioned schema plus guarantees—freshness, volume bounds, nullability, accepted values.

**Registration**: A consumer declaring "I depend on this contract."

**Proposal**: A producer requesting a breaking change. Triggers notifications to affected consumers.

**Acknowledgment**: A consumer responding to a proposal—approved, blocked, or migrating.

## The Name

In ancient Rome, a *tessera* was a token split between two parties to prove identity or agreement. Each half was meaningless alone. Matching edges proved the agreement was valid.

That's the producer/consumer relationship. Neither side works alone. Tessera makes the agreement explicit.

## Status

Early development.
