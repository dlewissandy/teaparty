// Identity helpers: resolve agent/member names and sender labels from store data.

let _store = null;

export function initIdentity(store) {
  _store = store;
}

export function isWorkgroupOwner(workgroupId) {
  const s = _store.get();
  const data = s.data.treeData[workgroupId];
  if (!data || !s.auth.user) return false;
  const self = data.members.find(m => m.user_id === s.auth.user.id);
  return self?.role === 'owner';
}

export function memberName(workgroupId, userId) {
  const data = _store.get().data.treeData[workgroupId];
  const member = data?.members.find(m => m.user_id === userId);
  if (!member) return userId?.slice(0, 8) || 'unknown';
  return member.name || member.email;
}

export function agentName(workgroupId, agentId) {
  const data = _store.get().data.treeData[workgroupId];
  const agent = data?.agents?.find(a => a.id === agentId);
  if (!agent) return agentId?.slice(0, 8) || 'agent';
  return agent.name || agent.id.slice(0, 8);
}

export function senderLabel(workgroupId, message) {
  const s = _store.get();
  if (message.sender_type === 'user') {
    if (s.auth.user && message.sender_user_id === s.auth.user.id) return 'You';
    return memberName(workgroupId, message.sender_user_id);
  }
  if (message.sender_agent_id) return agentName(workgroupId, message.sender_agent_id);
  if (message.sender_type === 'system') return 'System';
  return 'Agent';
}

export function senderInitials(workgroupId, message) {
  if (message.sender_type === 'agent') return 'AI';
  const label = senderLabel(workgroupId, message);
  return label.split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?';
}
