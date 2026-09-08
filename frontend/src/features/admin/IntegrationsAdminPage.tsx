import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { integrationService, type SupportedProvider } from '@/services/integrationService'

const CAPABILITIES = [
  ['communication', 'Communication'], ['payment', 'Payments'], ['document_storage', 'Document Storage'],
] as const

export default function IntegrationsAdminPage() {
  const queryClient = useQueryClient()
  const [capability, setCapability] = useState('communication')
  const [providerCode, setProviderCode] = useState('')
  const [environment, setEnvironment] = useState('TEST')
  const [connectionName, setConnectionName] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const providers = useQuery({ queryKey: ['supported-integrations'], queryFn: integrationService.providers })
  const connections = useQuery({ queryKey: ['integration-connections'], queryFn: integrationService.connections })
  const eligible = (providers.data ?? []).filter(provider => provider.capability === capability)
  const selected: SupportedProvider | undefined = eligible.find(provider => provider.provider_code === providerCode)
  const create = useMutation({
    mutationFn: () => integrationService.create({
      provider_code: providerCode, capability, environment, connection_name: connectionName || undefined,
      public_configuration: Object.fromEntries((selected?.public_fields ?? []).map(field => [field.field_code, values[field.field_code] ?? ''])),
      secrets: Object.fromEntries((selected?.secret_fields ?? []).map(field => [field.field_code, values[field.field_code] ?? ''])),
    }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['integration-connections'] }); setProviderCode(''); setConnectionName(''); setValues({}) },
  })
  const selectCapability = (next: string) => { setCapability(next); setProviderCode(''); setValues({}) }
  const fieldInput = (field: { field_code: string; label: string; required: boolean }, secret = false) => <label key={field.field_code} className="block text-sm font-medium text-gray-700">{field.label}{field.required ? ' *' : ''}<input aria-label={field.label} type={secret ? 'password' : 'text'} value={values[field.field_code] ?? ''} onChange={event => setValues(current => ({ ...current, [field.field_code]: event.target.value }))} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" /></label>

  return <div className="mx-auto max-w-6xl space-y-5 p-6">
    <div><h1 className="text-2xl font-bold text-gray-900">Integrations</h1><p className="mt-1 text-sm text-gray-500">Add and configure supported provider connections for this hospital.</p></div>
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
      <section className="overflow-hidden rounded-lg border border-gray-200 bg-white"><div className="border-b border-gray-200 px-5 py-4"><h2 className="font-semibold text-gray-900">Configured Connections</h2></div>{connections.isLoading ? <p className="p-5 text-sm text-gray-500">Loading connections...</p> : connections.data?.length ? <div className="divide-y divide-gray-100">{connections.data.map(connection => <div key={connection.id} className="flex items-center justify-between gap-3 px-5 py-4 text-sm"><div><p className="font-medium text-gray-900">{connection.connection_name || connection.provider}</p><p className="text-gray-500">{connection.capability} · {connection.environment}</p></div><span className="text-xs font-medium text-gray-600">{connection.status}</span></div>)}</div> : <p className="p-5 text-sm text-gray-500">No provider connections configured.</p>}</section>
      <section className="rounded-lg border border-gray-200 bg-white p-5"><h2 className="font-semibold text-gray-900">Add Integration</h2><form onSubmit={event => { event.preventDefault(); create.mutate() }} className="mt-4 space-y-4">
        <label className="block text-sm font-medium text-gray-700">Capability<select aria-label="Capability" value={capability} onChange={event => selectCapability(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">{CAPABILITIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="block text-sm font-medium text-gray-700">Provider<select aria-label="Provider" value={providerCode} onChange={event => { setProviderCode(event.target.value); setValues({}) }} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"><option value="">Select provider</option>{eligible.map(provider => <option key={provider.provider_code} value={provider.provider_code}>{provider.display_name}</option>)}</select></label>
        {selected && <><label className="block text-sm font-medium text-gray-700">Connection Name<input aria-label="Connection Name" value={connectionName} onChange={event => setConnectionName(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" /></label><label className="block text-sm font-medium text-gray-700">Environment<select aria-label="Environment" value={environment} onChange={event => setEnvironment(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">{selected.supported_environments.map(item => <option key={item}>{item}</option>)}</select></label><div className="space-y-3">{selected.public_fields.map(field => fieldInput(field))}</div><div className="border-t border-gray-200 pt-3 space-y-3">{selected.secret_fields.map(field => fieldInput(field, true))}</div><button type="submit" disabled={create.isPending} className="w-full rounded-lg bg-primary py-2.5 text-sm font-medium text-white disabled:opacity-50">{create.isPending ? 'Saving...' : 'Save Disabled Connection'}</button>{create.isError && <p role="alert" className="text-sm text-red-600">Could not save this connection. Check the registered fields.</p>}</>}
      </form></section>
    </div>
  </div>
}