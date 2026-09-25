import { useEffect, useState } from 'react'
import api from '../../api/client'
import { useAuth } from '../../context/AuthContext.jsx'
import { Loader2, Users as UsersIcon, ShieldCheck, ShieldOff } from 'lucide-react'

const ROLE_STYLE = {
  admin: 'text-rose-400 bg-rose-500/10 border-rose-500/20',
  verifier: 'text-brand-400 bg-brand-500/10 border-brand-500/20',
  surveyor: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
}

export default function UsersAdmin() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [updatingId, setUpdatingId] = useState(null)
  const { user: currentUser } = useAuth()

  function reload() {
    setLoading(true)
    api.get('/users').then((res) => setUsers(res.data)).finally(() => setLoading(false))
  }

  useEffect(() => { reload() }, [])

  async function updateRole(id, role) {
    setUpdatingId(id)
    try {
      const { data } = await api.patch(`/users/${id}`, { role })
      setUsers((prev) => prev.map((u) => (u.id === id ? data : u)))
    } catch (err) {
      alert(err.response?.data?.detail || 'Could not update role.')
    } finally {
      setUpdatingId(null)
    }
  }

  async function toggleActive(id, isActive) {
    setUpdatingId(id)
    try {
      const { data } = await api.patch(`/users/${id}`, { is_active: !isActive })
      setUsers((prev) => prev.map((u) => (u.id === id ? data : u)))
    } catch (err) {
      alert(err.response?.data?.detail || 'Could not update status.')
    } finally {
      setUpdatingId(null)
    }
  }

  return (
    <div className="animate-fade-in">
      <h1 className="font-display text-2xl font-bold text-white mb-1 flex items-center gap-2">
        <UsersIcon size={22} className="text-brand-400" /> Users
      </h1>
      <p className="text-sm text-slate-500 mb-8">Manage Surveyor, Verifier, and Admin accounts.</p>

      {loading && <div className="flex justify-center py-20"><Loader2 className="animate-spin text-brand-400" size={26} /></div>}

      {!loading && (
        <div className="card overflow-hidden">
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/5 text-left text-xs text-slate-500">
                  <th className="px-5 py-3 font-medium">Name</th>
                  <th className="px-5 py-3 font-medium">Email</th>
                  <th className="px-5 py-3 font-medium">Role</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const isSelf = u.id === currentUser?.id
                  return (
                    <tr key={u.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.02]">
                      <td className="px-5 py-3 text-white">{u.name}{isSelf && <span className="text-[10px] text-slate-500 ml-1.5">(you)</span>}</td>
                      <td className="px-5 py-3 text-slate-400">{u.email}</td>
                      <td className="px-5 py-3">
                        <select
                          value={u.role} disabled={updatingId === u.id}
                          onChange={(e) => updateRole(u.id, e.target.value)}
                          className={`badge border capitalize text-xs px-2 py-1 bg-transparent ${ROLE_STYLE[u.role]}`}
                        >
                          <option value="surveyor">Surveyor</option>
                          <option value="verifier">Verifier</option>
                          <option value="admin">Admin</option>
                        </select>
                      </td>
                      <td className="px-5 py-3">
                        {u.is_active ? (
                          <span className="badge bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"><ShieldCheck size={11} /> Active</span>
                        ) : (
                          <span className="badge bg-slate-500/10 text-slate-400 border border-slate-500/20"><ShieldOff size={11} /> Disabled</span>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <button
                          onClick={() => toggleActive(u.id, u.is_active)}
                          disabled={updatingId === u.id}
                          className="btn-secondary !py-1 !px-3 text-xs"
                        >
                          {updatingId === u.id ? <Loader2 size={12} className="animate-spin" /> : (u.is_active ? 'Disable' : 'Enable')}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="md:hidden divide-y divide-white/5">
            {users.map((u) => (
              <div key={u.id} className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-white text-sm font-medium">{u.name}</span>
                  {u.is_active ? (
                    <span className="badge bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"><ShieldCheck size={11} /> Active</span>
                  ) : (
                    <span className="badge bg-slate-500/10 text-slate-400 border border-slate-500/20"><ShieldOff size={11} /> Disabled</span>
                  )}
                </div>
                <div className="text-xs text-slate-500 mb-3">{u.email}</div>
                <div className="flex items-center gap-2">
                  <select
                    value={u.role} disabled={updatingId === u.id}
                    onChange={(e) => updateRole(u.id, e.target.value)}
                    className="input-field !py-1.5 !w-auto text-xs"
                  >
                    <option value="surveyor">Surveyor</option>
                    <option value="verifier">Verifier</option>
                    <option value="admin">Admin</option>
                  </select>
                  <button onClick={() => toggleActive(u.id, u.is_active)} disabled={updatingId === u.id} className="btn-secondary !py-1.5 text-xs">
                    {u.is_active ? 'Disable' : 'Enable'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
