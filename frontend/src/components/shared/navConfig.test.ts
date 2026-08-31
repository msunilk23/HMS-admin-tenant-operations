import { describe, expect, it } from 'vitest'
import { P34_PERMISSIONS } from '@/services/pharmacyDashboardService'
import { NAV_TREE, filterNavTree, findActiveDomainIds, findActiveSubsectionIds, isLeafActive, type NavAuthContext, type NavDomain } from './navConfig'

function ctx(overrides: Partial<NavAuthContext> = {}): NavAuthContext {
  return {
    role: '',
    hasFeature: () => true,
    hasPermission: () => true,
    ...overrides,
  }
}

function domainLabels(tree: ReturnType<typeof filterNavTree>): string[] {
  return tree.filter((entry): entry is NavDomain => entry.kind === 'domain').map((entry) => entry.label)
}

function leafLabels(tree: ReturnType<typeof filterNavTree>): string[] {
  const labels: string[] = []
  for (const entry of tree) {
    if (entry.kind === 'link') {
      labels.push(entry.label)
      continue
    }
    for (const child of entry.children) {
      if (child.kind === 'link') labels.push(child.label)
      else labels.push(...child.items.map((item) => item.label))
    }
  }
  return labels
}

describe('navConfig RBAC filtering', () => {
  it('hospital_admin sees the complete authorized hierarchy', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'hospital_admin' }))
    expect(domainLabels(tree)).toEqual([
      'Front Desk',
      'Clinical Care',
      'Laboratory',
      'Pharmacy',
      'Billing',
      'Requests',
      'Administration',
    ])
    expect(leafLabels(tree)).toEqual(
      expect.arrayContaining([
        'Patients', 'Register Visit', 'Appointments', 'OPD Queue',
        'Vitals', 'Nurse Roster', 'Consultation', 'Lab Results',
        'Lab Worklist', 'Pharmacy Dashboard', 'Dispensing', 'Patient Returns',
        'Supplier Returns', 'Stock Quarantine', 'Recall & Transfers', 'Inventory Counts',
        'Pharmacy Setup', 'Purchase Orders', 'Goods Receipts', 'Billing & Payments',
        'Indents', 'Doctor Registration', 'Schedules & Slots', 'Staff Users',
      ]),
    )
    expect(domainLabels(tree)).not.toContain('Platform Administration')
  })

  it('receptionist sees Front Desk but not Pharmacy or Administration', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'receptionist' }))
    expect(domainLabels(tree)).toEqual(['Front Desk', 'Requests'])
    expect(leafLabels(tree)).toEqual(['Dashboard', 'Patients', 'Register Visit', 'Appointments', 'OPD Queue', 'Indents'])
  })

  it('nurse sees Patients, Appointments, OPD Queue, Vitals, and Nurse Roster', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'nurse' }))
    expect(leafLabels(tree)).toEqual(
      expect.arrayContaining(['Patients', 'Appointments', 'OPD Queue', 'Vitals', 'Nurse Roster', 'Indents']),
    )
    expect(domainLabels(tree)).not.toContain('Pharmacy')
    expect(domainLabels(tree)).not.toContain('Administration')
  })

  it('doctor sees Patients, Appointments, Consultation, and Lab Results', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'doctor' }))
    expect(leafLabels(tree)).toEqual(
      expect.arrayContaining(['Patients', 'Appointments', 'Consultation', 'Lab Results', 'Indents']),
    )
    expect(leafLabels(tree)).not.toContain('Register Visit')
    expect(leafLabels(tree)).not.toContain('OPD Queue')
  })

  it('pharmacist sees only authorized Pharmacy children (no procurement)', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'pharmacist', hasPermission: () => true }))
    expect(leafLabels(tree)).toEqual(
      expect.arrayContaining([
        'Pharmacy Dashboard', 'Dispensing', 'Patient Returns', 'Supplier Returns',
        'Stock Quarantine', 'Recall & Transfers', 'Inventory Counts',
      ]),
    )
    expect(leafLabels(tree)).not.toEqual(
      expect.arrayContaining(['Pharmacy Setup', 'Purchase Orders', 'Goods Receipts']),
    )
  })

  it('store manager sees authorized inventory/procurement items but not dispensing or setup', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'store_manager' }))
    expect(leafLabels(tree)).toEqual(
      expect.arrayContaining(['Stock Quarantine', 'Recall & Transfers', 'Inventory Counts', 'Purchase Orders', 'Goods Receipts', 'Indents']),
    )
    expect(leafLabels(tree)).not.toContain('Dispensing')
    expect(leafLabels(tree)).not.toContain('Pharmacy Setup')
    expect(leafLabels(tree)).not.toContain('Pharmacy Dashboard')
  })

  it('auditor sees only explicitly permitted Pharmacy functionality', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'auditor' }))
    const pharmacy = tree.find((entry): entry is NavDomain => entry.kind === 'domain' && entry.id === 'pharmacy')
    expect(pharmacy).toBeDefined()
    expect(leafLabels([pharmacy!])).toEqual(['Inventory Counts'])
    // Auditor is not in ALL_STAFF for /indent, so Requests must not appear either.
    expect(domainLabels(tree)).toEqual(['Pharmacy'])
  })

  it('super admin sees Hospitals and no tenant operational groups', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'super_admin' }))
    expect(domainLabels(tree)).toEqual(['Platform Administration'])
    expect(leafLabels(tree)).toContain('Hospitals')
    expect(domainLabels(tree)).not.toEqual(
      expect.arrayContaining(['Front Desk', 'Clinical Care', 'Laboratory', 'Pharmacy', 'Billing', 'Requests', 'Administration']),
    )
  })

  it('hides groups and subsections with no visible children', () => {
    // Billing officer has no clinical/lab/administration access at all.
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'billing_officer' }))
    expect(domainLabels(tree)).toEqual(['Billing', 'Requests'])
  })

  it('hides Pharmacy Dashboard without the required P34 permission', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'pharmacist', hasPermission: () => false }))
    expect(leafLabels(tree)).not.toContain('Pharmacy Dashboard')
    expect(leafLabels(tree)).toContain('Dispensing')
  })

  it('shows Pharmacy Dashboard when the required P34 permission is present', () => {
    const tree = filterNavTree(
      NAV_TREE,
      ctx({ role: 'pharmacist', hasPermission: (key) => key === P34_PERMISSIONS.dashboard }),
    )
    expect(leafLabels(tree)).toContain('Pharmacy Dashboard')
  })

  it('continues to hide feature-disabled modules', () => {
    const tree = filterNavTree(
      NAV_TREE,
      ctx({ role: 'nurse', hasFeature: (key) => key !== 'vitals' }),
    )
    expect(leafLabels(tree)).not.toContain('Vitals')
    expect(leafLabels(tree)).toContain('Nurse Roster')
  })
})

describe('navConfig active-route matching', () => {
  it('matches Dispensing only on the exact /pharmacy path, not its sub-routes', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'hospital_admin' }))
    const pharmacy = tree.find((entry): entry is NavDomain => entry.kind === 'domain' && entry.id === 'pharmacy')!
    const operations = pharmacy.children.find((child) => child.kind === 'subsection' && child.id === 'pharmacy-operations')
    const dispensing = operations && operations.kind === 'subsection' ? operations.items.find((item) => item.id === 'dispensing') : undefined
    expect(dispensing).toBeDefined()
    expect(isLeafActive('/pharmacy', dispensing!)).toBe(true)
    expect(isLeafActive('/pharmacy/dashboard', dispensing!)).toBe(false)
  })

  it('activates Doctor Workspace/Consultation for dynamic consultation and prescription routes', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'doctor' }))
    expect(findActiveDomainIds(tree, '/doctor/consultation/abc-123')).toEqual(new Set(['clinical-care']))
    expect(findActiveDomainIds(tree, '/doctor/prescription/abc-123')).toEqual(new Set(['clinical-care']))

    const clinicalCare = tree.find((entry): entry is NavDomain => entry.kind === 'domain' && entry.id === 'clinical-care')!
    const doctorWorkspace = clinicalCare.children.find((child) => child.kind === 'subsection' && child.id === 'doctor-workspace')
    const consultation = doctorWorkspace && doctorWorkspace.kind === 'subsection' ? doctorWorkspace.items.find((item) => item.id === 'consultation') : undefined
    expect(consultation).toBeDefined()
    expect(isLeafActive('/doctor/prescription/abc-123', consultation!)).toBe(true)
  })

  it('activates Doctor Management for schedules regardless of query parameters', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'hospital_admin' }))
    // matchPath only ever receives pathname (query strings are stripped by the router),
    // so a schedules link with search params still maps to the same active domain.
    expect(findActiveDomainIds(tree, '/admin/doctors/schedules')).toEqual(new Set(['administration']))
  })

  it('activates only the subsection containing the active route, not sibling subsections', () => {
    const tree = filterNavTree(NAV_TREE, ctx({ role: 'doctor' }))
    expect(findActiveSubsectionIds(tree, '/doctor/consultation')).toEqual(new Set(['doctor-workspace']))
    expect(findActiveSubsectionIds(tree, '/doctor/consultation')).not.toContain('nursing')
  })
})
