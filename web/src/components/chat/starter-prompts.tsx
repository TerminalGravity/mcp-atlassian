"use client"

import { motion } from "framer-motion"
import {
  Sparkles,
  Users,
  Bug,
  Rocket,
  TrendingUp,
  MessageSquare
} from "lucide-react"

interface StarterPromptsProps {
  onSelect: (prompt: string) => void
}

const prompts = [
  {
    icon: Sparkles,
    label: "What is Changemaker?",
    prompt: "What is the Changemaker project and what features are being developed?",
    color: "from-violet-500 to-purple-500",
  },
  {
    icon: TrendingUp,
    label: "Recent activity",
    prompt: "What are the most recently updated issues across all projects?",
    color: "from-blue-500 to-cyan-500",
  },
  {
    icon: Bug,
    label: "Open bugs",
    prompt: "What bugs are currently open and who is working on them?",
    color: "from-red-500 to-orange-500",
  },
  {
    icon: Rocket,
    label: "AI initiatives",
    prompt: "What AI-related features or initiatives are being worked on?",
    color: "from-emerald-500 to-teal-500",
  },
  {
    icon: Users,
    label: "Team workload",
    prompt: "Show me the distribution of issues by assignee in the DS project",
    color: "from-amber-500 to-yellow-500",
  },
  {
    icon: MessageSquare,
    label: "API integrations",
    prompt: "What API integrations or endpoints have been implemented?",
    color: "from-pink-500 to-rose-500",
  },
]

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1,
    },
  },
}

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0 },
}

export function StarterPrompts({ onSelect }: StarterPromptsProps) {
  return (
    <div className="flex flex-col items-center justify-center py-8 px-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5 }}
        className="text-center mb-8"
      >
        <h2 className="text-2xl font-bold mb-2">
          Jira Knowledge Assistant
        </h2>
        <p className="text-muted-foreground">
          Search across 400K+ issues using natural language
        </p>
      </motion.div>

      <motion.div
        variants={container}
        initial="hidden"
        animate="show"
        className="grid grid-cols-2 md:grid-cols-3 gap-3 max-w-2xl w-full"
      >
        {prompts.map((p, i) => (
          <motion.button
            key={i}
            variants={item}
            whileHover={{ scale: 1.02, y: -2 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => onSelect(p.prompt)}
            className="group relative flex flex-col items-start gap-2 p-4 rounded-xl border bg-card text-left transition-all hover:border-primary/50 hover:shadow-lg"
          >
            <div className={`p-2 rounded-lg bg-gradient-to-br ${p.color} text-white`}>
              <p.icon className="w-4 h-4" />
            </div>
            <span className="text-sm font-medium group-hover:text-primary transition-colors">
              {p.label}
            </span>
            <div className="absolute inset-0 rounded-xl bg-gradient-to-br opacity-0 group-hover:opacity-5 transition-opacity pointer-events-none"
              style={{ background: `linear-gradient(to bottom right, var(--primary), transparent)` }}
            />
          </motion.button>
        ))}
      </motion.div>

      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.8 }}
        className="text-xs text-muted-foreground mt-6"
      >
        Or type your own question below
      </motion.p>
    </div>
  )
}
