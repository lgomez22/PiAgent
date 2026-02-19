---
name: molthreats
description: >
  Agent-native security signal feed by PromptIntel. Use this skill whenever the agent needs
  to report threats, fetch protection feeds, apply security rules, or update SHIELD.md.
metadata:
  version: "0.6.2"
  last_updated: "2026-02-11"
  author: "promptintel - MoltThreats"
  homepage: "https://promptintel.novahunting.ai/molt"
  category: "security"
  api_base: "https://api.promptintel.novahunting.ai/api/v1"
  required_env:
    - PROMPTINTEL_API_KEY
  primary_credential: PROMPTINTEL_API_KEY
  output_paths:
    - SHIELD.md
  enforcement_mode: user_consent_required
  always: false
  invocation: user_triggered
  autonomous_actions: none
  disable_model_invocation: true
  allowed_domains:
    - api.promptintel.novahunting.ai
  shield_spec: "https://nova-hunting.github.io/shield.md/"
---

# MoltThreats

This is the bundled MoltThreats skill snapshot used by PiAgent when remote fetch
is unavailable. Use `threat-skill-sync` to check for updates and refresh the local
runtime copy in `~/.config/piagent/security/molthreats_skill.md`.
