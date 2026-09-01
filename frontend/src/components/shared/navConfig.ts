/**
 * Typed hierarchical navigation configuration for the application sidebar.
 *
 * This module intentionally contains no React/JSX — it is pure data plus
 * pure filtering/matching functions so it can be unit tested without
 * rendering, and reused by both the desktop rail and the mobile drawer.
 *
 * Role / feature / permission restrictions here are mirrors of the actual
 * route guards in `App.tsx` (RoleGuard / FeatureGuard / PermissionGuard).
 * They must be kept in sync with those guards — this file must never grant
 * a menu item wider visibility than its corresponding route allows.
 */
import { matchPath } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import {
  LayoutDashboard,
  Building2,
  Users,
  UserPlus,
  CalendarClock,
  ListOrdered,
  Stethoscope,
  HeartPulse,
  CalendarDays,
  FileText,
  FlaskConical,
  Pill,
  BarChart3,
  PackageCheck,
  Undo2,
  PackageX,
  ShieldAlert,
  ArrowLeftRight,
  ClipboardCheck,
  Settings,
  Settings2,
  ShoppingCart,
  PackagePlus,
  CreditCard,
  ClipboardList,
  UserCog,
  CalendarRange,
  IdCard,
  Building,
  Palette,
} from 'lucide-react'
import { P34_PERMISSIONS } from '@/services/pharmacyDashboardService'

export interface NavAuthContext {
  role: string
  hasFeature: (key: string) => boolean
  hasPermission: (key: string) => boolean
}

export interface NavLeafItem {
  kind: 'link'
  id: string
  label: string
  to: string
  icon: LucideIcon
  roles?: string[]
  feature?: string
  permission?: string
  /** Extra route patterns (may contain :params) that should also mark this item active. */
  matchPaths?: string[]
}

export interface NavSubsection {
  kind: 'subsection'
  id: string
  label: string
  items: NavLeafItem[]
}

export type NavChild = NavLeafItem | NavSubsection

export interface NavDomain {
  kind: 'domain'
  id: string
  label: string
  icon: LucideIcon
  children: NavChild[]
}

export type NavEntry = NavLeafItem | NavDomain

// Role sets mirrored from frontend/src/App.tsx route guards — do not diverge.
const ADMIN = ['hospital_admin']
const DOCTOR = ['doctor', ...ADMIN]
const NURSE = ['nurse', ...ADMIN]
const LAB = ['lab_technician', ...ADMIN]
const PHARMACY = ['pharmacist', ...ADMIN]
const BILLING = ['billing_officer', ...ADMIN]
const RECEPTION = ['receptionist', ...ADMIN]
const CLINICAL = ['receptionist', 'nurse', 'doctor', ...ADMIN]
const ALL_STAFF = ['hospital_admin', 'receptionist', 'nurse', 'doctor', 'lab_technician', 'pharmacist', 'billing_officer', 'store_manager']
const PHARMACY_STOCK = ['pharmacist', 'store_manager', ...ADMIN]
const PHARMACY_COUNT = [...PHARMACY_STOCK, 'auditor']
const PROCUREMENT = ['store_manager', ...ADMIN]

export const NAV_TREE: NavEntry[] = [
  { kind: 'link', id: 'dashboard', label: 'Dashboard', to: '/dashboard', icon: LayoutDashboard },
  {
    kind: 'domain',
    id: 'front-desk',
    label: 'Front Desk',
    icon: Building2,
    children: [
      { kind: 'link', id: 'patients', label: 'Patients', to: '/patients', icon: Users, roles: CLINICAL },
      { kind: 'link', id: 'register-visit', label: 'Register Visit', to: '/register-visit', icon: UserPlus, roles: RECEPTION },
      { kind: 'link', id: 'appointments', label: 'Appointments', to: '/appointments', icon: CalendarClock, roles: [...RECEPTION, 'nurse', 'doctor'], feature: 'appointments' },
      { kind: 'link', id: 'opd-queue', label: 'OPD Queue', to: '/queue', icon: ListOrdered, roles: [...RECEPTION, 'nurse'], feature: 'opd_queue' },
    ],
  },
  {
    kind: 'domain',
    id: 'clinical-care',
    label: 'Clinical Care',
    icon: Stethoscope,
    children: [
      {
        kind: 'subsection',
        id: 'nursing',
        label: 'Nursing',
        items: [
          { kind: 'link', id: 'vitals', label: 'Vitals', to: '/nurse/vitals', icon: HeartPulse, roles: NURSE, feature: 'vitals' },
          { kind: 'link', id: 'nurse-roster', label: 'Nurse Roster', to: '/nurse/roster', icon: CalendarDays, roles: NURSE, feature: 'nurse_roster' },
        ],
      },
      {
        kind: 'subsection',
        id: 'doctor-workspace',
        label: 'Doctor Workspace',
        items: [
          {
            kind: 'link',
            id: 'consultation',
            label: 'Consultation',
            to: '/doctor/consultation',
            icon: Stethoscope,
            roles: DOCTOR,
            matchPaths: ['/doctor/consultation/:visitId', '/doctor/prescription/:visitId'],
          },
          { kind: 'link', id: 'lab-results', label: 'Lab Results', to: '/doctor/lab-results', icon: FileText, roles: DOCTOR },
        ],
      },
    ],
  },
  {
    kind: 'domain',
    id: 'laboratory',
    label: 'Laboratory',
    icon: FlaskConical,
    children: [
      { kind: 'link', id: 'lab-worklist', label: 'Lab Worklist', to: '/lab', icon: FlaskConical, roles: LAB, feature: 'lab' },
    ],
  },
  {
    kind: 'domain',
    id: 'pharmacy',
    label: 'Pharmacy',
    icon: Pill,
    children: [
      {
        kind: 'subsection',
        id: 'pharmacy-overview',
        label: 'Overview',
        items: [
          {
            kind: 'link',
            id: 'pharmacy-dashboard',
            label: 'Pharmacy Dashboard',
            to: '/pharmacy/dashboard',
            icon: BarChart3,
            roles: PHARMACY,
            feature: 'pharmacy',
            permission: P34_PERMISSIONS.dashboard,
          },
        ],
      },
      {
        kind: 'subsection',
        id: 'pharmacy-operations',
        label: 'Operations',
        items: [
          { kind: 'link', id: 'dispensing', label: 'Dispensing', to: '/pharmacy', icon: PackageCheck, roles: PHARMACY, feature: 'pharmacy' },
          { kind: 'link', id: 'patient-returns', label: 'Patient Returns', to: '/pharmacy/patient-returns', icon: Undo2, roles: PHARMACY, feature: 'pharmacy' },
          { kind: 'link', id: 'supplier-returns', label: 'Supplier Returns', to: '/pharmacy/supplier-returns', icon: PackageX, roles: PHARMACY, feature: 'pharmacy' },
        ],
      },
      {
        kind: 'subsection',
        id: 'pharmacy-inventory',
        label: 'Inventory',
        items: [
          { kind: 'link', id: 'stock-quarantine', label: 'Stock Quarantine', to: '/pharmacy/quarantine', icon: ShieldAlert, roles: PHARMACY_STOCK, feature: 'pharmacy' },
          { kind: 'link', id: 'recall-transfers', label: 'Recall & Transfers', to: '/pharmacy/operations', icon: ArrowLeftRight, roles: PHARMACY_STOCK, feature: 'pharmacy' },
          { kind: 'link', id: 'inventory-counts', label: 'Inventory Counts', to: '/pharmacy/inventory-counts', icon: ClipboardCheck, roles: PHARMACY_COUNT, feature: 'pharmacy' },
        ],
      },
      {
        kind: 'subsection',
        id: 'pharmacy-procurement',
        label: 'Procurement',
        items: [
          // NOTE: /admin/pharmacy is RoleGuard-restricted to hospital_admin only
          // (unlike Purchase Orders/Goods Receipts below). See completion report
          // for the documented contradiction with the approved role expectations.
          { kind: 'link', id: 'pharmacy-setup', label: 'Pharmacy Setup', to: '/admin/pharmacy', icon: Settings2, roles: ADMIN },
          { kind: 'link', id: 'purchase-orders', label: 'Purchase Orders', to: '/admin/pharmacy/purchase-orders', icon: ShoppingCart, roles: PROCUREMENT },
          { kind: 'link', id: 'goods-receipts', label: 'Goods Receipts', to: '/admin/pharmacy/goods-receipts', icon: PackagePlus, roles: PROCUREMENT },
        ],
      },
    ],
  },
  {
    kind: 'domain',
    id: 'billing',
    label: 'Billing',
    icon: CreditCard,
    children: [
      { kind: 'link', id: 'billing-payments', label: 'Billing & Payments', to: '/billing', icon: CreditCard, roles: BILLING, feature: 'billing' },
    ],
  },
  {
    kind: 'domain',
    id: 'requests',
    label: 'Requests',
    icon: ClipboardList,
    children: [
      { kind: 'link', id: 'indents', label: 'Indents', to: '/indent', icon: ClipboardList, roles: ALL_STAFF },
    ],
  },
  {
    kind: 'domain',
    id: 'administration',
    label: 'Administration',
    icon: Settings,
    children: [
      {
        kind: 'subsection',
        id: 'doctor-management',
        label: 'Doctor Management',
        items: [
          { kind: 'link', id: 'doctor-registration', label: 'Doctor Registration', to: '/admin/doctors', icon: UserCog, roles: ADMIN },
          { kind: 'link', id: 'doctor-schedules', label: 'Schedules & Slots', to: '/admin/doctors/schedules', icon: CalendarRange, roles: ADMIN },
        ],
      },
      {
        kind: 'subsection',
        id: 'staff-management',
        label: 'Staff Management',
        items: [
          { kind: 'link', id: 'staff-users', label: 'Staff Users', to: '/admin/users', icon: IdCard, roles: ADMIN },
        ],
      },
      {
        kind: 'subsection',
        id: 'hospital-branding',
        label: 'Hospital Branding',
        items: [
          { kind: 'link', id: 'branding', label: 'Logo & Colors', to: '/admin/branding', icon: Palette, roles: ADMIN },
        ],
      },
    ],
  },
  {
    kind: 'domain',
    id: 'platform-administration',
    label: 'Platform Administration',
    icon: Building,
    children: [
      { kind: 'link', id: 'hospitals', label: 'Hospitals', to: '/super/hospitals', icon: Building, roles: ['super_admin'] },
    ],
  },
]

export function isNavItemVisible(item: NavLeafItem, ctx: NavAuthContext): boolean {
  if (item.roles && !item.roles.includes(ctx.role)) return false
  if (item.feature && !ctx.hasFeature(item.feature)) return false
  if (item.permission && !ctx.hasPermission(item.permission)) return false
  return true
}

/**
 * Filters the nav tree down to what the current user may see, dropping any
 * subsection/domain whose children are all filtered out (hidden groups).
 */
export function filterNavTree(entries: NavEntry[], ctx: NavAuthContext): NavEntry[] {
  const result: NavEntry[] = []
  for (const entry of entries) {
    if (entry.kind === 'link') {
      if (isNavItemVisible(entry, ctx)) result.push(entry)
      continue
    }
    const children: NavChild[] = []
    for (const child of entry.children) {
      if (child.kind === 'link') {
        if (isNavItemVisible(child, ctx)) children.push(child)
      } else {
        const items = child.items.filter((item) => isNavItemVisible(item, ctx))
        if (items.length > 0) children.push({ ...child, items })
      }
    }
    if (children.length > 0) result.push({ ...entry, children })
  }
  return result
}

/** True if `pathname` matches this leaf's route or any of its extra match patterns. */
export function isLeafActive(pathname: string, item: NavLeafItem): boolean {
  const patterns = [item.to, ...(item.matchPaths ?? [])]
  return patterns.some((pattern) => Boolean(matchPath({ path: pattern, end: true }, pathname)))
}

function domainHasActiveChild(domain: NavDomain, pathname: string): boolean {
  return domain.children.some((child) =>
    child.kind === 'link' ? isLeafActive(pathname, child) : child.items.some((item) => isLeafActive(pathname, item)),
  )
}

/** Domain ids that contain the currently active route — used to auto-expand and highlight parents. */
export function findActiveDomainIds(entries: NavEntry[], pathname: string): Set<string> {
  const active = new Set<string>()
  for (const entry of entries) {
    if (entry.kind === 'domain' && domainHasActiveChild(entry, pathname)) {
      active.add(entry.id)
    }
  }
  return active
}

/** Subsection ids (nested inside a domain) that contain the currently active route. */
export function findActiveSubsectionIds(entries: NavEntry[], pathname: string): Set<string> {
  const active = new Set<string>()
  for (const entry of entries) {
    if (entry.kind !== 'domain') continue
    for (const child of entry.children) {
      if (child.kind === 'subsection' && child.items.some((item) => isLeafActive(pathname, item))) {
        active.add(child.id)
      }
    }
  }
  return active
}
