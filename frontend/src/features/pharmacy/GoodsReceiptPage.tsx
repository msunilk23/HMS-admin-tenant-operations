import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { goodsReceiptService } from "@/services/goodsReceiptService";
import { purchaseOrderService } from "@/services/purchaseOrderService";
import { masterDataService } from "@/services/masterDataService";

function money(value: string) {
  return Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default function GoodsReceiptPage() {
  const [selectedPo, setSelectedPo] = useState("");
  const [selectedGrn, setSelectedGrn] = useState("");
  const [selectedLocation, setSelectedLocation] = useState("");
  const [poItemId, setPoItemId] = useState("");
  const [receivedQuantity, setReceivedQuantity] = useState("");
  const [freeQuantity, setFreeQuantity] = useState("0");
  const [batchNumber, setBatchNumber] = useState("");
  const [manufacturingDate, setManufacturingDate] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [error, setError] = useState("");
  const qc = useQueryClient();
  const { data: orders = [] } = useQuery({
    queryKey: ["grn-eligible-pos"],
    queryFn: () => purchaseOrderService.list(),
  });
  const { data: receipts = [], isLoading } = useQuery({
    queryKey: ["goods-receipts"],
    queryFn: () => goodsReceiptService.list(),
  });
  const { data: products = [] } = useQuery({
    queryKey: ["grn-products"],
    queryFn: () => masterDataService.listMedicineProducts(),
  });
  const { data: locations = [] } = useQuery({
    queryKey: ["grn-locations"],
    queryFn: goodsReceiptService.locations,
  });
  useEffect(() => {
    if (!selectedLocation && locations.length === 1)
      setSelectedLocation(locations[0].id);
  }, [locations, selectedLocation]);
  const createMutation = useMutation({
    mutationFn: () => {
      const location = locations.find((item) => item.id === selectedLocation);
      if (!location) throw new Error("Select an active pharmacy location");
      return goodsReceiptService.create({
        purchase_order_id: selectedPo,
        facility_id: location.facility_id,
        pharmacy_location_id: location.id,
        received_date: new Date().toISOString().slice(0, 10),
      });
    },
    onSuccess: (receipt) => {
      setSelectedGrn(receipt.id);
      setSelectedPo("");
      setError("");
      qc.invalidateQueries({ queryKey: ["goods-receipts"] });
    },
    onError: (value: Error) => setError(value.message),
  });
  const receiveMutation = useMutation({
    mutationFn: () =>
      goodsReceiptService.receiveItem(selectedGrn, {
        purchase_order_item_id: poItemId,
        received_quantity: Number(receivedQuantity),
        free_quantity: Number(freeQuantity),
        batch_number: batchNumber,
        manufacturing_date: manufacturingDate || undefined,
        expiry_date: expiryDate,
      }),
    onSuccess: () => {
      setPoItemId("");
      setReceivedQuantity("");
      setFreeQuantity("0");
      setBatchNumber("");
      setManufacturingDate("");
      setExpiryDate("");
      setError("");
      qc.invalidateQueries({ queryKey: ["goods-receipts"] });
    },
    onError: (value: Error) => setError(value.message),
  });
  const finalizeMutation = useMutation({
    mutationFn: () => goodsReceiptService.finalize(selectedGrn),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["goods-receipts"] }),
    onError: (value: Error) => setError(value.message),
  });
  const cancelMutation = useMutation({
    mutationFn: () =>
      goodsReceiptService.cancel(
        selectedGrn,
        "Cancelled by receiving administrator",
      ),
    onSuccess: () => {
      setSelectedGrn("");
      qc.invalidateQueries({ queryKey: ["goods-receipts"] });
    },
    onError: (value: Error) => setError(value.message),
  });
  const order = orders.find((item) => item.id === selectedPo);
  const receipt = receipts.find((item) => item.id === selectedGrn);
  const productName = (id: string) => {
    const product = products.find((item) => item.id === id);
    return product
      ? `${product.code} · ${product.brand_name ?? "Generic"} ${product.strength ?? ""}`
      : id;
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Goods Receipts</h1>
        <p className="text-sm text-gray-500 mt-1">
          Receive approved purchase orders with batch and expiry details.
        </p>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_420px] gap-5 items-start">
        <section className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="p-4 border-b border-gray-200">
            <h2 className="font-semibold">Receipts</h2>
          </div>
          {isLoading ? (
            <p className="p-5 text-sm text-gray-500">Loading receipts…</p>
          ) : (
            <div className="divide-y divide-gray-100">
              {receipts.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  onClick={() => setSelectedGrn(item.id)}
                  className={`w-full text-left p-4 hover:bg-gray-50 ${selectedGrn === item.id ? "bg-primary/5" : ""}`}
                >
                  <div className="flex justify-between">
                    <span className="font-semibold">{item.grn_number}</span>
                    <span className="text-xs font-semibold">{item.status}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    PO {item.purchase_order_id} · {item.items.length} receipt
                    item(s)
                  </p>
                  <p className="text-sm mt-2">
                    Total: ₹{money(item.total_amount)}
                  </p>
                </button>
              ))}
              {receipts.length === 0 && (
                <p className="p-5 text-sm text-gray-500">
                  No goods receipts found.
                </p>
              )}
            </div>
          )}
        </section>
        <section className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <h2 className="font-semibold">Receive purchase order</h2>
          <label className="block text-sm text-gray-700">
            Pharmacy location
            <select
              value={selectedLocation}
              onChange={(event) => setSelectedLocation(event.target.value)}
              className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
            >
              <option value="">Select location</option>
              {locations
                .filter((item) => item.active)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.location_code} · {item.location_name}
                  </option>
                ))}
            </select>
          </label>
          {locations.length === 0 && (
            <p className="border-l-4 border-amber-500 bg-amber-50 p-3 text-sm text-amber-900">
              Create a pharmacy location in Pharmacy Master Data, then sign in
              again before receiving stock.
            </p>
          )}
          <label className="block text-sm text-gray-700">
            Sent purchase order
            <select
              value={selectedPo}
              onChange={(event) => setSelectedPo(event.target.value)}
              className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2"
            >
              <option value="">Select PO</option>
              {orders
                .filter((item) =>
                  ["SENT", "PARTIALLY_RECEIVED"].includes(item.status),
                )
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.po_number} · {item.status}
                  </option>
                ))}
            </select>
          </label>
          {selectedPo && (
            <button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={!selectedLocation || createMutation.isPending}
              className="w-full rounded-lg bg-primary text-white py-2.5 text-sm disabled:opacity-50"
            >
              {createMutation.isPending ? "Creating…" : "Create draft GRN"}
            </button>
          )}
          {receipt && receipt.status === "DRAFT" && (
            <div className="border-t border-gray-100 pt-4 space-y-3">
              <h3 className="font-medium">Add received batch</h3>
              <select
                value={poItemId}
                onChange={(event) => setPoItemId(event.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">Select PO item</option>
                {(
                  order?.items ??
                  orders.find((item) => item.id === receipt.purchase_order_id)
                    ?.items ??
                  []
                ).map((item) => (
                  <option key={item.id} value={item.id}>
                    {productName(item.medicine_product_id)} · ordered{" "}
                    {item.ordered_quantity}
                  </option>
                ))}
              </select>
              <div className="grid grid-cols-2 gap-2">
                <input
                  value={receivedQuantity}
                  onChange={(event) => setReceivedQuantity(event.target.value)}
                  type="number"
                  min="0"
                  step="0.001"
                  placeholder="Received qty"
                  className="border border-gray-300 rounded-lg px-3 py-2"
                />
                <input
                  value={freeQuantity}
                  onChange={(event) => setFreeQuantity(event.target.value)}
                  type="number"
                  min="0"
                  step="0.001"
                  placeholder="Free qty"
                  className="border border-gray-300 rounded-lg px-3 py-2"
                />
              </div>
              <input
                value={batchNumber}
                onChange={(event) => setBatchNumber(event.target.value)}
                placeholder="Batch number"
                className="w-full border border-gray-300 rounded-lg px-3 py-2"
              />
              <div className="grid grid-cols-2 gap-2">
                <label className="text-xs text-gray-600">
                  Manufactured
                  <input
                    value={manufacturingDate}
                    onChange={(event) =>
                      setManufacturingDate(event.target.value)
                    }
                    type="date"
                    className="mt-1 w-full border border-gray-300 rounded-lg px-2 py-2"
                  />
                </label>
                <label className="text-xs text-gray-600">
                  Expires
                  <input
                    value={expiryDate}
                    onChange={(event) => setExpiryDate(event.target.value)}
                    type="date"
                    className="mt-1 w-full border border-gray-300 rounded-lg px-2 py-2"
                  />
                </label>
              </div>
              <button
                type="button"
                onClick={() => receiveMutation.mutate()}
                disabled={receiveMutation.isPending}
                className="w-full rounded-lg border border-primary text-primary py-2.5 text-sm"
              >
                {receiveMutation.isPending ? "Recording…" : "Record batch"}
              </button>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => finalizeMutation.mutate()}
                  disabled={
                    finalizeMutation.isPending || receipt.items.length === 0
                  }
                  className="flex-1 rounded-lg bg-emerald-600 text-white py-2 text-sm"
                >
                  Finalize
                </button>
                <button
                  type="button"
                  onClick={() => cancelMutation.mutate()}
                  className="flex-1 rounded-lg border border-red-200 text-red-600 py-2 text-sm"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
          {receipt && receipt.items.length > 0 && (
            <div className="border-t border-gray-100 pt-3 space-y-2">
              <h3 className="font-medium">Recorded batches</h3>
              {receipt.items.map((item) => (
                <div
                  key={item.id}
                  className="text-xs bg-gray-50 rounded-lg p-2 flex justify-between"
                >
                  <span>
                    {item.batch_number} · expires {item.expiry_date}
                  </span>
                  <span>{item.received_quantity}</span>
                </div>
              ))}
            </div>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </section>
      </div>
    </div>
  );
}
