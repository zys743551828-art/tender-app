import type { ChangePackageFactScope, PackageExecutionInputView, PackageFactScopeObservation, PackageFactScopeView } from "../../src/contracts";
import { frozenManifestDigest } from "../../src/packageFrozenInput";
export const scopeId=(n:number)=>`00000000-0000-0000-0000-${String(n).padStart(12,"0")}`;
export function scopeObservation(prepared:PackageExecutionInputView,fact:string,head:PackageFactScopeView|null=null,changed=false):PackageFactScopeObservation{
  const b=prepared.manifest.identity.binding;
  return {kind:"fact_scope_observation",bid_id:b.bid_id,package_id:b.package_id,revision_id:b.revision_id,inventory_id:b.inventory_id,frozen_input_id:b.frozen_input_id,execution_input_id:prepared.manifest.id,execution_input_digest:prepared.digest,fact_id:fact,prepared_context_digest:b.context_digest,observed_context_digest:changed?"f".repeat(64):b.context_digest,matches_prepared_input:!changed,provenance_status:changed?"unproven":"verified",subject_choices:[
    {kind:"engineering_project",id:scopeId(60),label:"合成工程 · 名称只作展示"},
    {kind:"lot",id:scopeId(61),label:"合成标段 A"},
    {kind:"round",id:scopeId(62),label:"第1轮"},
    {kind:"bidder",id:scopeId(63),label:"合成投标主体"},
  ],head,binding_status:head?.manifest.action==="withdraw"?"withdrawn":head&&!changed?"matches_current_input":"unproven",observation_gap:null,checked_at:"2026-10-20T08:00:00.000001Z",facts_qualified:false,review_ready:false,launch_available:false,publication_authorized:false};
}
export async function scopeReply(prepared:PackageExecutionInputView,body:ChangePackageFactScope,actor:string,id:string,previous:PackageFactScopeView|null=null):Promise<PackageFactScopeView>{
  const manifest:PackageFactScopeView["manifest"]={version:"package-fact-scope/1",kind:"fact_scope_declaration",id,actor_id:actor,command_id:id,recorded_at:"2026-10-20T08:01:00.000001Z",reason:body.reason,action:body.action,previous_digest:body.previous_digest,
    binding:{...prepared.manifest.identity.binding,execution_input_id:prepared.manifest.id,execution_input_digest:prepared.digest,facts_digest:prepared.manifest.execution_context.facts_digest,fact_set_id:prepared.manifest.execution_context.fact_set_id!,fact_id:body.fact_id,fact_item_digest:"a".repeat(64),proof_digest:"b".repeat(64)},
    subject:body.subject??previous?.manifest.subject??{kind:"lot",id:scopeId(61)},facts_qualified:false,review_ready:false,launch_available:false,publication_authorized:false};
  return {manifest,digest:await frozenManifestDigest(manifest)};
}
