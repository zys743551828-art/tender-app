import type { BidPage } from "./contracts";
import { useDirectory } from "./useDirectory";

export function useBidChoices() {
  return useDirectory<BidPage>("/bids?limit=100");
}
