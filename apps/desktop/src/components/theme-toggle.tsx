import { Moon, Sun } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTheme } from '@/lib/theme'

/** One click between light and dark. Settings → Appearance also offers "follow the system". */
export function ThemeToggle() {
  const { theme, setPreference } = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`Switch to ${next} theme`}
      onClick={() => {
        setPreference(next)
      }}
    >
      {theme === 'dark' ? <Sun /> : <Moon />}
    </Button>
  )
}
