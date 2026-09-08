import { useState } from 'react'
import { isAxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { integrationService, type IntegrationConnection, type SupportedProvider } from '@/services/integrationService'

const CAPABILITIES = [['communication', 'Communication'], ['payment', 'Payments'], ['document_storage', 'Document Storage']] as const
type Field = { field_code: string; label: string; required: boolean }

function errorMessage(error: unknown, fallback: string) {
  return isAxiosError(error) ? error.response?.data?.detail ?? error.message : fallback
}

export default function IntegrationsAdminPage() {
  const queryClient = useQueryClient()
  const [capability, setCapability] = useState('communication')
  const [providerCode, setProviderCode] = useState('')
  const [environment, setEnvironment] = useState('TEST')
  const [connectionName, setConnectionName] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [detailsId, setDetailsId] = useState<string | null>(null)
  const [editing, setEditing] = useState<IntegrationConnection | null>(null)
  const [editName, setEditName] = useState('')
  const [editEnvironment, setEditEnvironment] = useState('TEST')
  const [editPublicValues, setEditPublicValues] = useState<Record<string, string>>({})
  const [editSecrets, setEditSecrets] = useState<Record<string, string>>({})
  const providers = useQuery({ queryKey: ['supported-integrations'], queryFn: integrationService.providers })
  const connections = useQuery({ queryKey: ['integration-connections'], queryFn: integrationService.connections })
  const eligible = (providers.data ?? []).filter(provider => provider.capability === capability)
  const selected: SupportedProvider | undefined = eligible.find(provider => provider.provider_code === providerCode)
  const refreshConnections = () => queryClient.invalidateQueries({ queryKey: ['integration-connections'] })
  const create = useMutation({
    mutationFn: () => integrationService.create({
      provider_code: providerCode, capability, environment, connection_name: connectionName || undefined,
      public_configuration: Object.fromEntries((selected?.public_fields ?? []).map(field => [field.field_code, values[field.field_code] ?? ''])),
      secrets: Object.fromEntries((selected?.secret_fields ?? []).map(field => [field.field_code, values[field.field_code] ?? ''])),
    }),
    onSuccess: () => { refreshConnections(); setProviderCode(''); setConnectionName(''); setValues({}) },
  })
  const edit = useMutation({
    mutationFn: async () => {
      if (!editing) throw new Error('No integration selected')
      await integrationService.update(editing.provider, { environment: editEnvironment, connection_name: editName, public_configuration: editPublicValues })
      for (const [credentialType, secret] of Object.entries(editSecrets)) {
        if (secret.trim()) await integrationService.rotateSecret(editing.provider, { environment: editEnvironment, credential_type: credentialType, secret })
      }
    },
    onSuccess: () => { refreshConnections(); setEditing(null); setEditSecrets({}) },
  })
  const toggle = useMutation({
    mutationFn: ({ connection, action }: { connection: IntegrationConnection; action: 'enable' | 'disable' }) => action === 'enable' ? integrationService.enable(connection.provider) : integrationService.disable(connection.provider),
    onSuccess: refreshConnections,
  })
  const fieldInput = (field: Field, secret = false) => <label key={field.field_code} className="block text-sm font-medium text-gray-700">{field.label}{field.required ? ' *' : ''}<input aria-label={field.label} type={secret ? 'password' : 'text'} value={values[field.field_code] ?? ''} onChange={event => setValues(current => ({ ...current, [field.field_code]: event.target.value }))} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" /></label>
  const beginEdit = (connection: IntegrationConnection) => { setEditing(connection); setEditName(connection.connection_name ?? ''); setEditEnvironment(connection.environment); setEditPublicValues(connection.public_configuration); setEditSecrets({}) }
  const selectCapability = (next: string) => { setCapability(next); setProviderCode(''); setValues({}) }

  return <div className="mx-auto max-w-6xl space-y-5 p-6">
    <div><h1 className="text-2xl font-bold text-gray-900">Integrations</h1><p className="mt-1 text-sm text-gray-500">Add and configure supported provider connections for this hospital.</p></div>
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
      <section className="overflow-hidden rounded-lg border border-gray-200 bg-white"><div className="border-b border-gray-200 px-5 py-4"><h2 className="font-semibold text-gray-900">Configured Connections</h2></div>
        {connections.isLoading ? <p className="p-5 text-sm text-gray-500">Loading connections...</p> : connections.data?.length ? <div className="divide-y divide-gray-100">{connections.data.map(connection => <div key={connection.id} className="px-5 py-4 text-sm"><div className="flex items-start justify-between gap-3"><div><p className="font-medium text-gray-900">{connection.connection_name || connection.provider}</p><p className="text-gray-500">{connection.provider} · {connection.capability} · {connection.environment}</p></div><span className="text-xs font-medium text-gray-600">{connection.status}</span></div>
          {detailsId === connection.id && <div className="mt-3 rounded-md bg-gray-50 p-3 text-xs text-gray-600"><p className="font-medium text-gray-700">Public configuration</p>{Object.entries(connection.public_configuration).map(([key, value]) => <p key={key} className="mt-1"><span className="font-medium">{key}:</span> {value}</p>)}<p className="mt-2"><span className="font-medium">Secrets:</span> configured and write-only</p><p className="mt-1"><span className="font-medium">Credential version:</span> {connection.credential_version ?? 1}</p></div>}
          <div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => setDetailsId(detailsId === connection.id ? null : connection.id)} className="rounded border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-700">{detailsId === connection.id ? 'Hide details' : 'View details'}</button><button type="button" onClick={() => beginEdit(connection)} className="rounded border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-700">Amend</button><button type="button" onClick={() => toggle.mutate({ connection, action: connection.status === 'DISABLED' ? 'enable' : 'disable' })} disabled={toggle.isPending} className="rounded border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-700">{connection.status === 'DISABLED' ? 'Enable' : 'Disable'}</button></div>
        </div>)}</div> : <p className="p-5 text-sm text-gray-500">No provider connections configured.</p>}
        {toggle.isError && <p role="alert" className="border-t border-red-100 px-5 py-3 text-sm text-red-600">{errorMessage(toggle.error, 'Could not change the integration status.')}</p>}
      </section>
      <section className="rounded-lg border border-gray-200 bg-white p-5"><h2 className="font-semibold text-gray-900">{editing ? `Amend ${editing.provider}` : 'Add Integration'}</h2>
        {editing ? <form onSubmit={event => { event.preventDefault(); edit.mutate() }} className="mt-4 space-y-4"><label className="block text-sm font-medium text-gray-700">Connection Name<input aria-label="Edit Connection Name" value={editName} onChange={event => setEditName(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" /></label><label className="block text-sm font-medium text-gray-700">Environment<select aria-label="Edit Environment" value={editEnvironment} disabled className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"><option>TEST</option><option>LIVE</option></select></label>{Object.entries(editPublicValues).map(([key, value]) => <label key={key} className="block text-sm font-medium text-gray-700">{key}<input aria-label={`Edit ${key}`} value={value} onChange={event => setEditPublicValues(current => ({ ...current, [key]: event.target.value }))} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" /></label>)}<div className="border-t border-gray-200 pt-3"><p className="text-sm font-medium text-gray-700">Rotate secrets</p><p className="mt-1 text-xs text-gray-500">Existing secrets are hidden. Leave blank to keep them unchanged.</p>{['key_secret', 'webhook_secret'].map(key => <label key={key} className="mt-3 block text-sm font-medium text-gray-700">{key}<input aria-label={`Rotate ${key}`} type="password" value={editSecrets[key] ?? ''} onChange={event => setEditSecrets(current => ({ ...current, [key]: event.target.value }))} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" /></label>)}</div><div className="flex gap-2"><button type="submit" disabled={edit.isPending} className="flex-1 rounded-lg bg-primary py-2.5 text-sm font-medium text-white disabled:opacity-50">{edit.isPending ? 'Saving...' : 'Save changes'}</button><button type="button" onClick={() => setEditing(null)} className="rounded-lg border border-gray-300 px-3 text-sm font-medium text-gray-700">Cancel</button></div>{edit.isError && <p role="alert" className="text-sm text-red-600">{errorMessage(edit.error, 'Could not amend this connection.')}</p>}</form> : <form onSubmit={event => { event.preventDefault(); create.mutate() }} className="mt-4 space-y-4"><label className="block text-sm font-medium text-gray-700">Capability<select aria-label="Capability" value={capability} onChange={event => selectCapability(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">{CAPABILITIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="block text-sm font-medium text-gray-700">Provider<select aria-label="Provider" value={providerCode} onChange={event => { setProviderCode(event.target.value); setValues({}) }} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"><option value="">Select provider</option>{eligible.map(provider => <option key={provider.provider_code} value={provider.provider_code}>{provider.display_name}</option>)}</select></label>{selected && <><label className="block text-sm font-medium text-gray-700">Connection Name<input aria-label="Connection Name" value={connectionName} onChange={event => setConnectionName(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" /></label><label className="block text-sm font-medium text-gray-700">Environment<select aria-label="Environment" value={environment} onChange={event => setEnvironment(event.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">{selected.supported_environments.map(item => <option key={item}>{item}</option>)}</select></label><div className="space-y-3">{selected.public_fields.map(field => fieldInput(field))}</div><div className="border-t border-gray-200 pt-3 space-y-3">{selected.secret_fields.map(field => fieldInput(field, true))}</div><button type="submit" disabled={create.isPending} className="w-full rounded-lg bg-primary py-2.5 text-sm font-medium text-white disabled:opacity-50">{create.isPending ? 'Saving...' : 'Save Disabled Connection'}</button>{create.isError && <p role="alert" className="text-sm text-red-600">{errorMessage(create.error, 'Could not save this connection.')}</p>}</>}</form>}
      </section>
    </div>
  </div>
}