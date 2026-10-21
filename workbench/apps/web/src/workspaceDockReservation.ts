type Reservation = {
  attribute: string | null;
  space: string;
  owners: Map<symbol, number | null>;
};

const reservations = new Map<HTMLElement, Reservation>();

function apply(target: HTMLElement, entry: Reservation) {
  const width = [...entry.owners.values()]
    .reverse()
    .find((value) => value !== null);
  if (width !== undefined) {
    target.setAttribute("data-assistant-docked", "true");
    target.style.setProperty("--assistant-dock-space", `${width}px`);
  } else {
    if (entry.attribute === null)
      target.removeAttribute("data-assistant-docked");
    else target.setAttribute("data-assistant-docked", entry.attribute);
    if (entry.space)
      target.style.setProperty("--assistant-dock-space", entry.space);
    else target.style.removeProperty("--assistant-dock-space");
  }
}

/** A closing panel must not erase the room reserved by its replacement. */
export function reserveWorkspaceDock(target: HTMLElement, owner: symbol) {
  let entry = reservations.get(target);
  if (!entry) {
    entry = {
      attribute: target.getAttribute("data-assistant-docked"),
      space: target.style.getPropertyValue("--assistant-dock-space"),
      owners: new Map(),
    };
    reservations.set(target, entry);
  }
  entry.owners.set(owner, null);
  return () => {
    const current = reservations.get(target);
    if (!current) return;
    current.owners.delete(owner);
    apply(target, current);
    if (!current.owners.size) reservations.delete(target);
  };
}

export function setWorkspaceDockWidth(
  target: HTMLElement,
  owner: symbol,
  width: number | null,
) {
  const entry = reservations.get(target);
  if (!entry?.owners.has(owner)) return;
  entry.owners.set(owner, width);
  apply(target, entry);
}
