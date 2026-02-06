"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Search } from "lucide-react"
import { cn } from "@/lib/utils"
import { UserSelector } from "./user-selector"
import { ThemeToggle } from "./theme-toggle"
import { Badge } from "@/components/ui/badge"

const NAV_LINKS = [
  { href: "/", label: "Chat" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/my-work", label: "My Work" },
  { href: "/settings", label: "Settings" },
]

export function Nav() {
  const pathname = usePathname()

  return (
    <nav className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="max-w-5xl mx-auto px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-6">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-primary/80 shadow-sm">
              <Search className="w-4 h-4 text-primary-foreground" />
            </div>
            <div className="hidden sm:block">
              <span className="font-semibold text-sm">Jira Knowledge</span>
              <Badge variant="secondary" className="ml-2 text-[9px] font-normal py-0">
                AI
              </Badge>
            </div>
          </Link>

          {/* Nav Links */}
          <div className="flex items-center gap-1">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "px-3 py-1.5 text-sm rounded-lg transition-colors",
                  pathname === link.href
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted"
                )}
              >
                {link.label}
              </Link>
            ))}
          </div>
        </div>

        {/* Right side controls */}
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <UserSelector />
        </div>
      </div>
    </nav>
  )
}
