import { useState } from "react";
import { ErrorNotice } from "./components";
import type { EngineeringRoundPage } from "./contracts";
import { ResourceState } from "./ResourceState";
import { useCommand } from "./useCommand";
import { useDirectory } from "./useDirectory";

type Lot = { id: string; engineering_project_id: string; label: string };
type LotPage = { items: Lot[]; has_more: boolean; next_cursor: string | null };
type Round = EngineeringRoundPage["items"][number];

export function ProjectLotRegistration({
  engineeringId,
  onRegistered,
}: {
  engineeringId: string;
  onRegistered: (round: Round) => void;
}) {
  const lots = useDirectory<LotPage>(
    `/identity/lots?engineering_project_id=${encodeURIComponent(engineeringId)}&limit=100`,
  );
  const [lotId, setLotId] = useState("");
  const [created, setCreated] = useState<Lot | null>(null);
  const [label, setLabel] = useState("");
  const [lotReason, setLotReason] = useState("");
  const [number, setNumber] = useState("");
  const [roundReason, setRoundReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const lotCommand = useCommand(`register-lot:${engineeringId}`);
  const roundCommand = useCommand(`register-round:${engineeringId}`);
  const options = lots.items.filter(
    (lot) => lot.engineering_project_id === engineeringId,
  );
  if (created && !options.some((lot) => lot.id === created.id))
    options.unshift(created);
  const selected = options.find((lot) => lot.id === lotId);
  const roundNo = Number(number);
  const duplicate = options.some((lot) => lot.label === label.trim());
  const canRegisterLot =
    !!lots.data &&
    !lots.error &&
    !lots.loading &&
    !!label.trim() &&
    !!lotReason.trim();
  const canRegisterRound =
    !!selected &&
    Number.isSafeInteger(roundNo) &&
    roundNo > 0 &&
    roundNo <= 2147483647 &&
    !!roundReason.trim();
  async function registerLot() {
    if (!canRegisterLot) return;
    setError(null);
    const result = await lotCommand.run<Lot>(
      "/identity/lots",
      {
        engineering_project_id: engineeringId,
        label: label.trim(),
        reason: lotReason.trim(),
      },
      null,
    );
    if (!result) return;
    const lot = result.data;
    if (
      !lot?.id ||
      lot.engineering_project_id !== engineeringId ||
      lot.label !== label.trim()
    ) {
      setError(
        new Error("登记结果与所选工程或标段不一致，请重新核对工程目录。"),
      );
      return;
    }
    setCreated(lot);
    setLotId(lot.id);
    setNumber("");
    setRoundReason("");
    setLabel("");
    setLotReason("");
    void lots.reload();
  }
  async function registerRound() {
    if (!selected || !canRegisterRound) return;
    setError(null);
    const result = await roundCommand.run<Round>(
      "/identity/rounds",
      {
        engineering_project_id: engineeringId,
        lot_id: selected.id,
        round_no: roundNo,
        reason: roundReason.trim(),
      },
      null,
    );
    if (!result) return;
    const round = result.data;
    if (
      !round?.id ||
      round.engineering_project_id !== engineeringId ||
      round.lot_id !== selected.id ||
      round.round_no !== roundNo
    ) {
      setError(
        new Error("登记结果与所选工程、标段或轮次不一致，请重新核对工程目录。"),
      );
      return;
    }
    setNumber("");
    setRoundReason("");
    onRegistered(round);
  }
  return (
    <fieldset
      disabled={lotCommand.busy || roundCommand.busy}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target instanceof HTMLInputElement)
          event.preventDefault();
      }}
    >
      <legend>补登工程标段与轮次</legend>
      <p className="small-note">
        先查看已有标段与轮次。仅在目录缺项时根据招标文件补登。登记会写入工程目录，项目归属和投标主体需在下方另行确认。
      </p>
      <ResourceState
        {...lots}
        hasData={!!lots.data}
        onRetry={() => void lots.reload()}
      />
      <label>
        已登记标段
        <select
          value={lotId}
          onChange={(event) => {
            setLotId(event.target.value);
            setNumber("");
            setRoundReason("");
            setError(null);
          }}
        >
          <option value="">请选择标段</option>
          {options.map((lot) => (
            <option key={lot.id} value={lot.id}>
              {lot.label}
              {options.some(
                (other) => other.id !== lot.id && other.label === lot.label,
              )
                ? ` · ${lot.id}`
                : ""}
            </option>
          ))}
        </select>
      </label>
      {lots.hasMore && (
        <button
          type="button"
          className="text-button"
          disabled={lots.moreBusy}
          onClick={() => void lots.loadMore()}
        >
          加载更多已登记标段
        </button>
      )}
      <ErrorNotice
        error={lots.moreError}
        onRetry={() => void lots.loadMore()}
      />
      {!selected && (
        <>
          <label>
            新标段名称或编号
            <input
              value={label}
              maxLength={200}
              onChange={(event) => setLabel(event.target.value)}
            />
          </label>
          <label>
            标段登记依据
            <input
              value={lotReason}
              maxLength={1000}
              onChange={(event) => setLotReason(event.target.value)}
              placeholder="例如：招标文件页码、条款及标段编号"
            />
          </label>
          {duplicate && (
            <p className="small-note">
              目录已有同名标段。若指同一标段，请从上方选择；若确属另一标段，请在登记依据中写明区别。
            </p>
          )}
          <button
            type="button"
            className="button secondary"
            disabled={!canRegisterLot}
            onClick={() => void registerLot()}
          >
            登记工程标段
          </button>
          <ErrorNotice error={lotCommand.error} />
        </>
      )}
      {selected && (
        <>
          <label>
            要登记的招标轮次
            <input
              type="number"
              min={1}
              max={2147483647}
              step={1}
              value={number}
              onChange={(event) => setNumber(event.target.value)}
            />
          </label>
          <label>
            轮次登记依据
            <input
              value={roundReason}
              maxLength={1000}
              onChange={(event) => setRoundReason(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="button secondary"
            disabled={!canRegisterRound}
            onClick={() => void registerRound()}
          >
            登记并选用此轮次
          </button>
          <ErrorNotice error={roundCommand.error} />
        </>
      )}
      <ErrorNotice error={error} />
    </fieldset>
  );
}
