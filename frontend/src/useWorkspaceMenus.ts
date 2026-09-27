import { useEffect } from 'react'

/** Native details menus should dismiss without stealing focus from the next action. */
export function useWorkspaceMenus(viewKey: string) {
  useEffect(() => {
    const menus = () => document.querySelectorAll<HTMLDetailsElement>('details[data-workspace-menu][open]')
    const close = (menu: HTMLDetailsElement, restoreFocus = false) => {
      const hadFocus = menu.contains(document.activeElement)
      menu.open = false
      if (restoreFocus && hadFocus) menu.querySelector<HTMLElement>('summary')?.focus()
    }
    menus().forEach(menu => close(menu))
    const outside = (event: Event) => {
      if (!(event.target instanceof Node)) return
      menus().forEach(menu => { if (!menu.contains(event.target as Node)) close(menu) })
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) menus().forEach(menu => close(menu, true))
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('click', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('click', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [viewKey])
}
