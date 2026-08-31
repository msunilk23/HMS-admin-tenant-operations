import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useAuthStore } from '@/features/auth/authStore'
import { usePharmacyCapabilities } from '@/hooks/usePharmacyCapabilities'
import {
  NAV_TREE,
  filterNavTree,
  isLeafActive,
  findActiveDomainIds,
  type NavDomain,
  type NavLeafItem,
} from './navConfig'

const COLLAPSED_STORAGE_KEY = 'hms.sidebar.collapsed'

function readStoredCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

interface NavLeafRowProps {
  item: NavLeafItem
  isExpanded: boolean
  pathname: string
  indent: boolean
  onSelect: () => void
}

function NavLeafRow({ item, isExpanded, pathname, indent, onSelect }: NavLeafRowProps) {
  const active = isLeafActive(pathname, item)
  const Icon = item.icon
  const layout = isExpanded ? `${indent ? 'pl-8' : 'px-3'} pr-3` : 'justify-center px-0'
  const border = isExpanded ? (active ? 'border-l-2 border-primary' : 'border-l-2 border-transparent') : ''
  const state = active ? 'bg-primary/10 text-primary font-medium' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'

  return (
    <Link
      to={item.to}
      onClick={onSelect}
      title={!isExpanded ? item.label : undefined}
      aria-current={active ? 'page' : undefined}
      className={`flex items-center gap-3 rounded-lg py-2 text-sm transition-colors ${layout} ${border} ${state}`}
    >
      <Icon className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
      {isExpanded && <span className="truncate whitespace-nowrap">{item.label}</span>}
    </Link>
  )
}

interface DomainRowProps {
  domain: NavDomain
  isExpanded: boolean
  isOpen: boolean
  isDomainActive: boolean
  pathname: string
  onToggle: () => void
  onSelectLeaf: () => void
}

function DomainRow({ domain, isExpanded, isOpen, isDomainActive, pathname, onToggle, onSelectLeaf }: DomainRowProps) {
  const Icon = domain.icon
  const showChildren = isExpanded && isOpen
  const domainId = `nav-domain-${domain.id}`

  const activate = () => onToggle()

  return (
    <div>
      <button
        type="button"
        onClick={activate}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            activate()
          }
        }}
        aria-expanded={isOpen}
        aria-controls={domainId}
        title={!isExpanded ? domain.label : undefined}
        className={`flex w-full items-center gap-3 rounded-lg py-2 text-sm font-medium transition-colors ${
          isExpanded ? 'px-3' : 'justify-center px-0'
        } ${isDomainActive ? 'text-primary' : 'text-gray-700 hover:bg-gray-100'}`}
      >
        <Icon className="h-5 w-5 flex-shrink-0" aria-hidden="true" />
        {isExpanded && <span className="flex-1 truncate text-left">{domain.label}</span>}
        {isExpanded &&
          (isOpen ? (
            <ChevronDown className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
          ))}
      </button>
      {showChildren && (
        <ul id={domainId} className="mt-0.5 space-y-0.5">
          {domain.children.map((child) =>
            child.kind === 'link' ? (
              <li key={child.id}>
                <NavLeafRow item={child} isExpanded={isExpanded} pathname={pathname} indent onSelect={onSelectLeaf} />
              </li>
            ) : (
              <li key={child.id}>
                <p className="mt-2 px-3 pb-0.5 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  {child.label}
                </p>
                <ul className="space-y-0.5">
                  {child.items.map((item) => (
                    <li key={item.id}>
                      <NavLeafRow item={item} isExpanded={isExpanded} pathname={pathname} indent onSelect={onSelectLeaf} />
                    </li>
                  ))}
                </ul>
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  )
}

interface SidebarProps {
  mobileOpen: boolean
  onCloseMobile: () => void
}

export default function Sidebar({ mobileOpen, onCloseMobile }: SidebarProps) {
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const hasFeature = useAuthStore((s) => s.hasFeature)
  const { hasPermission } = usePharmacyCapabilities(Boolean(user) && hasFeature('pharmacy'))

  const [collapsed, setCollapsed] = useState<boolean>(readStoredCollapsed)
  const [hovered, setHovered] = useState(false)
  const [expandedDomains, setExpandedDomains] = useState<Set<string>>(new Set())

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_STORAGE_KEY, String(collapsed))
    } catch {
      // Ignore storage failures (private browsing, quota, etc.)
    }
  }, [collapsed])

  const tree = filterNavTree(NAV_TREE, { role: user?.role ?? '', hasFeature, hasPermission })
  const activeDomainIds = findActiveDomainIds(tree, location.pathname)

  // Auto-open the parent hierarchy of the current route. Only adds ids —
  // never removes — so manually expanded domains stay open across navigation.
  useEffect(() => {
    setExpandedDomains((previous) => {
      const next = new Set(previous)
      let changed = false
      activeDomainIds.forEach((id) => {
        if (!next.has(id)) {
          next.add(id)
          changed = true
        }
      })
      return changed ? next : previous
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  const isExpanded = mobileOpen || !collapsed || hovered

  const toggleDomain = (id: string) => {
    setExpandedDomains((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleDomainToggle = (id: string) => {
    // Collapsed rail: activating (click or keyboard) a domain expands the
    // sidebar instead of relying on hover, so it stays usable without a mouse.
    if (collapsed && !hovered && !mobileOpen) setCollapsed(false)
    toggleDomain(id)
  }

  return (
    <>
      {mobileOpen && <div className="fixed inset-0 z-30 bg-black/30 lg:hidden" onClick={onCloseMobile} aria-hidden="true" />}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex flex-shrink-0 flex-col overflow-hidden border-r border-gray-200 bg-white transition-all duration-200 lg:static lg:z-auto ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        } ${isExpanded ? 'w-[270px]' : 'w-[68px]'}`}
        onMouseEnter={() => { if (collapsed) setHovered(true) }}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => { if (collapsed) setHovered(true) }}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node)) setHovered(false)
        }}
      >
        <div className="flex h-14 flex-shrink-0 items-center justify-start border-b border-gray-200 px-3">
          <button
            type="button"
            onClick={() => { setCollapsed((c) => !c); setHovered(false) }}
            className="rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <PanelLeftOpen className="h-5 w-5" aria-hidden="true" /> : <PanelLeftClose className="h-5 w-5" aria-hidden="true" />}
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-3" aria-label="Primary">
          <ul className="space-y-0.5">
            {tree.map((entry) => (
              <li key={entry.id}>
                {entry.kind === 'link' ? (
                  <NavLeafRow item={entry} isExpanded={isExpanded} pathname={location.pathname} indent={false} onSelect={onCloseMobile} />
                ) : (
                  <DomainRow
                    domain={entry}
                    isExpanded={isExpanded}
                    isOpen={expandedDomains.has(entry.id)}
                    isDomainActive={activeDomainIds.has(entry.id)}
                    pathname={location.pathname}
                    onToggle={() => handleDomainToggle(entry.id)}
                    onSelectLeaf={onCloseMobile}
                  />
                )}
              </li>
            ))}
          </ul>
        </nav>
      </aside>
    </>
  )
}
