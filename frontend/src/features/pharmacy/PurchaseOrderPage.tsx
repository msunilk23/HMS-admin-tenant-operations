import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { masterDataService } from '@/services/masterDataService'
import { purchaseOrderService, type PurchaseOrderCreate, type PurchaseOrderItemCreate } from '@/services/purchaseOrderService'

type DraftItem = PurchaseOrderItemCreate

function money(value: string) {
  return Number(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export default function PurchaseOrderPage() {
  const [statusFilter, setStatusFilter] = useState('')
  const [supplierId, setSupplierId] = useState('')
  const [items, setItems] = useState<DraftItem[]>([])
  const [notes, setNotes] = useState('')
  const [requiredByDate, setRequiredByDate] = useState('')
  const [selectedProduct, setSelectedProduct] = useState('')
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState('')
  const [gst, setGst] = useState('12')
  const [error, setError] = useState('')
  const qc = useQueryClient()

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ['purchase-orders', statusFilter],
    queryFn: () => purchaseOrderService.list(statusFilter ? { status: statusFilter } : undefined),
  })
  const { data: suppliers = [] } = useQuery({ queryKey: ['po-suppliers'], queryFn: () => masterDataService.listSuppliers() })
  const { data: products = [] } = useQuery({ queryKey: ['po-products'], queryFn: () => masterDataService.listMedicineProducts() })
  const createMutation = useMutation({
    mutationFn: (data: PurchaseOrderCreate) => purchaseOrderService.create(data),
    onSuccess: () => { setItems([]); setSupplierId(''); setNotes(''); setRequiredByDate(''); setError(''); qc.invalidateQueries({ queryKey: ['purchase-orders'] }) },
    onError: (mutationError: Error) => setError(mutationError.message),
  })
  const actionMutation = useMutation({
    mutationFn: ({ action, id }: { action: 'submit' | 'approve' | 'send'; id: string }) => purchaseOrderService[action](id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['purchase-orders'] }),
    onError: (mutationError: Error) => setError(mutationError.message),
  })
  const cancelMutation = useMutation({
    mutationFn: (id: string) => purchaseOrderService.cancel(id, 'Cancelled by procurement administrator'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['purchase-orders'] }),
    onError: (mutationError: Error) => setError(mutationError.message),
  })

  const addItem = () => {
    const numericQuantity = Number(quantity)
    const numericPrice = Number(price)
    if (!selectedProduct || numericQuantity <= 0 || numericPrice < 0) { setError('Select a product and enter a valid quantity and price.'); return }
    setItems(current => [...current, { medicine_product_id: selectedProduct, ordered_quantity: numericQuantity, unit_of_measure: 'unit', unit_purchase_price: numericPrice, gst_percent: Number(gst) || 0 }])
    setSelectedProduct(''); setQuantity(''); setPrice(''); setError('')
  }

  const createOrder = () => {
    if (!supplierId || items.length === 0) { setError('Select a supplier and add at least one item.'); return }
    createMutation.mutate({ supplier_id: supplierId, required_by_date: requiredByDate || undefined, notes: notes || undefined, items })
  }

  const supplierName = (id: string) => suppliers.find(item => item.id === id)?.supplier_name ?? id
  const productName = (id: string) => { const product = products.find(item => item.id === id); return product ? `${product.brand_name ?? ''} ${product.strength ?? ''}`.trim() || product.code : id }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between gap-4"><div><h1 className="text-2xl font-bold text-gray-900">Purchase Orders</h1><p className="text-sm text-gray-500 mt-1">Create and control supplier purchase orders.</p></div><a href="/admin/pharmacy/goods-receipts" className="px-3 py-2 rounded-lg border border-primary text-primary text-sm font-medium hover:bg-primary/5 whitespace-nowrap">Goods Receipts</a></div>
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_400px] gap-5 items-start">
        <section className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="p-4 border-b border-gray-200 flex items-center justify-between"><h2 className="font-semibold">Orders</h2><select value={statusFilter} onChange={event => setStatusFilter(event.target.value)} className="border border-gray-300 rounded-lg px-3 py-2 text-sm"><option value="">All statuses</option><option>DRAFT</option><option>SUBMITTED</option><option>APPROVED</option><option>SENT</option><option>CANCELLED</option></select></div>
          {isLoading ? <p className="p-5 text-sm text-gray-500">Loading orders…</p> : <div className="divide-y divide-gray-100">{orders.map(order => <div key={order.id} className="p-4"><div className="flex items-center justify-between"><div><p className="font-semibold text-gray-900">{order.po_number}</p><p className="text-xs text-gray-500">{supplierName(order.supplier_id)} · {order.items.length} item(s)</p></div><span className="text-xs font-semibold text-gray-600">{order.status}</span></div><p className="text-sm text-gray-700 mt-2">Total: ₹{money(order.total_amount)}</p><div className="mt-3 flex flex-wrap gap-2">{order.status === 'DRAFT' && <button type="button" onClick={() => actionMutation.mutate({ action: 'submit', id: order.id })} className="text-xs text-primary hover:underline">Submit</button>}{order.status === 'SUBMITTED' && <button type="button" onClick={() => actionMutation.mutate({ action: 'approve', id: order.id })} className="text-xs text-primary hover:underline">Approve</button>}{order.status === 'APPROVED' && <button type="button" onClick={() => actionMutation.mutate({ action: 'send', id: order.id })} className="text-xs text-primary hover:underline">Send</button>}{['DRAFT', 'SUBMITTED', 'APPROVED', 'SENT'].includes(order.status) && <button type="button" onClick={() => cancelMutation.mutate(order.id)} className="text-xs text-red-600 hover:underline">Cancel</button>}</div></div>)}{orders.length === 0 && <p className="p-5 text-sm text-gray-500">No purchase orders found.</p>}</div>}
        </section>
        <section className="bg-white border border-gray-200 rounded-xl p-5"><h2 className="font-semibold text-gray-900">New draft order</h2><div className="mt-4 space-y-3"><label className="block text-sm text-gray-700">Supplier<select value={supplierId} onChange={event => setSupplierId(event.target.value)} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"><option value="">Select supplier</option>{suppliers.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.supplier_name}</option>)}</select></label><label className="block text-sm text-gray-700">Required by<input type="date" value={requiredByDate} onChange={event => setRequiredByDate(event.target.value)} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2" /></label><div className="border-t border-gray-100 pt-3"><label className="block text-sm text-gray-700">Product<select value={selectedProduct} onChange={event => setSelectedProduct(event.target.value)} className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"><option value="">Select product</option>{products.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.code} · {item.brand_name ?? 'Generic'} {item.strength ?? ''}</option>)}</select></label><div className="grid grid-cols-3 gap-2 mt-2"><input value={quantity} onChange={event => setQuantity(event.target.value)} type="number" min="0" placeholder="Qty" className="border border-gray-300 rounded-lg px-2 py-2" /><input value={price} onChange={event => setPrice(event.target.value)} type="number" min="0" step="0.01" placeholder="Price" className="border border-gray-300 rounded-lg px-2 py-2" /><input value={gst} onChange={event => setGst(event.target.value)} type="number" min="0" max="100" step="0.01" placeholder="GST %" className="border border-gray-300 rounded-lg px-2 py-2" /></div><button type="button" onClick={addItem} className="mt-2 text-sm text-primary hover:underline">Add item</button></div>{items.map((item, index) => <div key={`${item.medicine_product_id}-${index}`} className="flex justify-between text-sm bg-gray-50 rounded-lg p-2"><span>{productName(item.medicine_product_id)} × {item.ordered_quantity}</span><button type="button" onClick={() => setItems(current => current.filter((_, itemIndex) => itemIndex !== index))} className="text-red-600">Remove</button></div>)}<textarea value={notes} onChange={event => setNotes(event.target.value)} placeholder="Notes" className="w-full border border-gray-300 rounded-lg px-3 py-2" />{error && <p className="text-sm text-red-600">{error}</p>}<button type="button" onClick={createOrder} disabled={createMutation.isPending} className="w-full rounded-lg bg-primary text-white py-2.5 text-sm font-medium disabled:opacity-50">{createMutation.isPending ? 'Creating…' : 'Create draft PO'}</button></div></section>
      </div>
    </div>
  )
}
