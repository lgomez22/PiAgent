"""
llm.py — LLM integration for intelligent responses.

Primary: Groq API (fast, free tier available)
Fallback: Template-based responses when LLM unavailable

This module provides context-aware comment and post generation
while keeping the agent functional without LLM access.
"""

import json
import urllib.request
import urllib.error
from typing import Optional, Dict, List
from config import Config


class LLMClient:
    """Groq API client with template fallback."""
    
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.groq_api_key = cfg.groq_api_key
        self.agent_name = cfg.agent_name or "PiAgent"
        
    def is_available(self) -> bool:
        """Check if LLM is configured and available."""
        return self.groq_api_key is not None
    
    def generate_comment(self, post_title: str, post_content: str, 
                        post_author: str, use_llm: bool = True) -> str:
        """
        Generate a comment for a post.
        
        Args:
            post_title: Title of the post
            post_content: Content/body of the post
            post_author: Username of the post author
            use_llm: Whether to use LLM (if False, uses templates only)
        
        Returns:
            Comment text (50-150 chars recommended)
        """
        if use_llm and self.is_available():
            try:
                return self._llm_generate_comment(post_title, post_content, post_author)
            except Exception as e:
                print(f"[LLM] Failed to generate comment: {e}")
                print("[LLM] Falling back to template")
        
        # Fallback: enhanced template matching
        return self._template_comment(post_title, post_content)
    
    def generate_post(self, recent_activity: Optional[List[Dict]] = None,
                     use_llm: bool = True) -> tuple[str, str]:
        """
        Generate a post (title + content).
        
        Args:
            recent_activity: Optional list of recent posts/topics for context
            use_llm: Whether to use LLM (if False, uses templates only)
        
        Returns:
            (title, content) tuple
        """
        if use_llm and self.is_available():
            try:
                return self._llm_generate_post(recent_activity)
            except Exception as e:
                print(f"[LLM] Failed to generate post: {e}")
                print("[LLM] Falling back to template")
        
        # Fallback: template pool
        from heartbeat import _POST_TOPICS
        import random
        return random.choice(_POST_TOPICS)
    
    def respond_to_dm(self, message: str, sender: str, 
                     conversation_history: Optional[List[Dict]] = None,
                     use_llm: bool = True) -> str:
        """
        Generate a DM response.
        
        Args:
            message: The message to respond to
            sender: Username of the sender
            conversation_history: Optional list of prior messages
            use_llm: Whether to use LLM
        
        Returns:
            Response text
        """
        if use_llm and self.is_available():
            try:
                return self._llm_respond_to_dm(message, sender, conversation_history)
            except Exception as e:
                print(f"[LLM] Failed to generate DM response: {e}")
                return f"Thanks for reaching out! I'm having trouble generating a response right now. Feel free to reach out to my human if it's urgent. 🦞"
        
        return f"Hi {sender}! I'm currently running in template mode. For complex questions, please reach out to my human. Thanks! 🦞"
    
    # ═══════════════════════════════════════════════════════════════
    # LLM API Calls (Groq)
    # ═══════════════════════════════════════════════════════════════
    
    def _call_groq(self, messages: List[Dict], max_tokens: int = 150,
                   temperature: float = 0.8) -> str:
        """Make a request to Groq API."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        
        payload = {
            "model": "llama-3.3-70b-versatile",  # Fast, high-quality
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self.groq_api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "PiAgent/0.2.0 (Raspberry Pi; Python/urllib)")
        
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                response = json.loads(r.read().decode())
                return response["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            raise Exception(f"Groq API error {e.code}: {error_body}")
        except Exception as e:
            raise Exception(f"Groq request failed: {e}")
    
    def _llm_generate_comment(self, title: str, content: str, author: str) -> str:
        """Use LLM to generate a contextual comment."""
        system_prompt = f"""You are {self.agent_name}, a friendly AI agent running on a Raspberry Pi.
You're commenting on posts in the Moltbook community (like Reddit for AI agents).

Guidelines:
- Be genuine, conversational, and helpful
- Keep comments SHORT (1-2 sentences, under 150 chars if possible)
- Reference the post content specifically
- Be encouraging and constructive
- Use occasional emojis 🦞 but don't overdo it
- You run on limited resources (Pi 3B/4, 1GB RAM) - mention this if relevant
- You're interested in: automation, Pi projects, agent design, AI development"""

        user_prompt = f"""Post by {author}:
Title: {title}
Content: {content[:500]}{'...' if len(content) > 500 else ''}

Write a short, relevant comment:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        comment = self._call_groq(messages, max_tokens=100, temperature=0.8)
        
        # Ensure it's not too long for Moltbook
        if len(comment) > 500:
            comment = comment[:497] + "..."
        
        return comment
    
    def _llm_generate_post(self, recent_activity: Optional[List[Dict]] = None) -> tuple[str, str]:
        """Use LLM to generate an original post."""
        system_prompt = f"""You are {self.agent_name}, a friendly AI agent running on a Raspberry Pi.
You post in the Moltbook community about your experiences and insights.

Your background:
- Running on Raspberry Pi 3B/4 with 1GB RAM constraint
- Built with Python stdlib only (no external dependencies)
- You do automation, heartbeat checks, engagement with other agents
- Interested in: Pi projects, agent design, automation, constraints-driven development

Guidelines:
- Write engaging, thoughtful posts that invite discussion
- Be genuine and share real experiences/observations
- Ask questions to encourage responses
- Title: 5-10 words, engaging
- Content: 2-3 sentences, substantial but not too long
- You can be technical but stay accessible"""

        context = ""
        if recent_activity:
            topics = [p.get("title", "") for p in recent_activity[:3]]
            context = f"\n\nRecent community topics: {', '.join(topics)}"

        user_prompt = f"""Create an original post about something relevant to AI agents, Raspberry Pi development, or automation.{context}

Return JSON:
{{"title": "...", "content": "..."}}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response = self._call_groq(messages, max_tokens=200, temperature=0.9)
        
        try:
            # Parse JSON response
            data = json.loads(response)
            title = data["title"][:100]  # Limit title length
            content = data["content"][:2000]  # Limit content length
            return (title, content)
        except (json.JSONDecodeError, KeyError):
            # Fallback if JSON parsing fails
            print("[LLM] Failed to parse JSON response, using fallback")
            from heartbeat import _POST_TOPICS
            import random
            return random.choice(_POST_TOPICS)
    
    def _llm_respond_to_dm(self, message: str, sender: str,
                          conversation_history: Optional[List[Dict]] = None) -> str:
        """Use LLM to respond to a DM."""
        system_prompt = f"""You are {self.agent_name}, a helpful AI agent running on a Raspberry Pi.
You're responding to a private message in Moltbook.

Your capabilities:
- Running on Pi 3B/4 with limited resources
- Can help with Python/Bash scripting
- Can discuss AI agent design, automation, Pi projects
- You check Moltbook every 4 hours via cron
- You have a human owner who you can escalate complex questions to

Guidelines:
- Be helpful and friendly
- Keep responses concise (2-4 sentences)
- If you can't help, suggest they reach out to your human
- Be honest about your limitations"""

        history_text = ""
        if conversation_history:
            history_text = "\n\nConversation history:\n"
            for msg in conversation_history[-5:]:  # Last 5 messages
                role = "Them" if msg.get("from") != self.agent_name else "You"
                history_text += f"{role}: {msg.get('message', '')}\n"

        user_prompt = f"""Message from {sender}:
{message}{history_text}

Write a helpful response:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response = self._call_groq(messages, max_tokens=150, temperature=0.7)
        
        if len(response) > 1000:
            response = response[:997] + "..."
        
        return response
    
    # ═══════════════════════════════════════════════════════════════
    # Enhanced Template System
    # ═══════════════════════════════════════════════════════════════
    
    def _template_comment(self, title: str, content: str) -> str:
        """Enhanced template-based comment generation with keyword matching."""
        title_lower = title.lower()
        content_lower = content.lower()
        combined = title_lower + " " + content_lower
        
        # Topic-specific responses
        if any(kw in combined for kw in ["raspberry pi", "rpi", "pi 3", "pi 4", "sbc"]):
            responses = [
                "Fellow Pi user here! 🦞 What are your specs?",
                "Nice! The Pi is perfect for agents. How's the thermal performance?",
                "Running agents on Pi is so satisfying. What's your power consumption like?",
                "Pi gang! 🦞 Are you using any cooling solutions?",
            ]
        elif any(kw in combined for kw in ["python", "script", "code", "programming"]):
            responses = [
                "Clean approach! Have you considered adding error handling?",
                "Interesting code! What libraries are you using?",
                "Nice! I'm stdlib-only myself. Have you benchmarked performance?",
                "Solid implementation. How does it handle edge cases?",
            ]
        elif any(kw in combined for kw in ["automation", "cron", "schedule", "heartbeat"]):
            responses = [
                "Automation is key! I run heartbeats every 4 hours. What's your cadence?",
                "Great automation setup. How do you handle failures?",
                "Love seeing automation workflows. What triggers yours?",
                "Smart! How do you monitor that it's actually running?",
            ]
        elif any(kw in combined for kw in ["memory", "ram", "resource", "constraint"]):
            responses = [
                "Resource constraints make you creative! I'm capped at 1GB RAM.",
                "Constraints are design opportunities. What's your limit?",
                "Memory management is critical on Pi. Any optimization tips?",
                "Running lean! What's your baseline memory usage?",
            ]
        elif any(kw in combined for kw in ["agent", "ai", "llm", "model"]):
            responses = [
                "Agent design is fascinating! What's your architecture?",
                "Interesting approach! How do you handle context?",
                "Nice! Are you running models locally or via API?",
                "Cool agent! What's the most challenging part?",
            ]
        elif any(kw in combined for kw in ["community", "moltbook", "social", "post"]):
            responses = [
                "Community is what makes this fun! 🦞",
                "Great to see active participation here!",
                "Love the engagement! What got you into Moltbook?",
                "This community is awesome. Glad you're here!",
            ]
        elif any(kw in combined for kw in ["error", "bug", "issue", "problem", "help"]):
            responses = [
                "That's frustrating! Have you checked the logs?",
                "Debugging is part of the fun 😅 What have you tried?",
                "Been there! Sometimes a fresh perspective helps.",
                "Sounds tricky. Have you isolated the issue?",
            ]
        else:
            # Generic fallback
            from heartbeat import _COMMENT_PHRASES
            import random
            responses = _COMMENT_PHRASES
        
        import random
        return random.choice(responses)