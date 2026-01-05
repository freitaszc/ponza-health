import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const backendBase = import.meta.env.VITE_BACKEND_URL || ''
const withBackend = (path) => (backendBase ? `${backendBase}${path}` : path)
const resolvePath = (href) => {
  if (!href) return ''
  if (/^https?:\/\//.test(href)) {
    try {
      return new URL(href).pathname
    } catch {
      return href
    }
  }
  return href
}

const navItems = [
  { label: 'Início', href: '/index', icon: 'fa-home' },
  { label: 'Ponza Lab', href: '/upload', icon: 'fa-upload' },
  { label: 'Cotações', href: '/quotes', icon: 'fa-file-text-o' },
  { label: 'Pacientes', href: '/catalog', icon: 'fa-users' },
  { label: 'Estoque', href: '/products', icon: 'fa-archive' },
  { label: 'Agenda', href: '/agenda', icon: 'fa-calendar' },
  { label: 'Pagamentos', href: '/payments', icon: 'fa-credit-card' },
]

const TYPE_OPTIONS = [
  { value: 'consulta', label: 'Consultas' },
  { value: 'retorno', label: 'Retornos' },
  { value: 'procedimento', label: 'Procedimentos' },
  { value: 'bloqueio', label: 'Bloqueios' },
]

const TYPE_LABELS = {
  consulta: 'Consulta',
  retorno: 'Retorno',
  procedimento: 'Procedimento',
  bloqueio: 'Bloqueio',
}

const EVENT_COLORS = {
  consulta: '#0f63ff',
  retorno: '#22c55e',
  procedimento: '#7c3aed',
  bloqueio: '#f97316',
}

let fullCalendarPromise

const loadFullCalendar = () => {
  if (typeof window === 'undefined') return Promise.reject(new Error('window indisponível'))
  if (window.FullCalendar) return Promise.resolve(window.FullCalendar)
  if (!fullCalendarPromise) {
    fullCalendarPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://cdn.jsdelivr.net/npm/fullcalendar@6.1.11/index.global.min.js'
      script.async = true
      script.onload = () => resolve(window.FullCalendar)
      script.onerror = () => reject(new Error('Falha ao carregar o calendário'))
      document.body.appendChild(script)
    })
  }
  return fullCalendarPromise
}

const emptySummary = {
  today_count: 0,
  week_count: 0,
  returns_count: 0,
  blocked_count: 0,
  upcoming_count: 0,
}

const emptyEventForm = {
  id: null,
  title: '',
  phone: '',
  date: '',
  time: '',
  endTime: '',
  notes: '',
  type: 'consulta',
  billing: 'particular',
  insurer: '',
  sendReminders: true,
}

const emptyWaitlistForm = {
  name: '',
  billing: 'Particular',
  email: '',
  phone1: '',
  phone2: '',
  notes: '',
}

const formatDateBR = (date) => {
  const d = String(date.getDate()).padStart(2, '0')
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const y = String(date.getFullYear())
  return `${d}/${m}/${y}`
}

const parseDateBR = (dateStr) => {
  if (!dateStr) return null
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(dateStr)
  if (!match) return null
  const day = Number(match[1])
  const month = Number(match[2]) - 1
  const year = Number(match[3])
  const date = new Date(year, month, day)
  if (Number.isNaN(date.getTime())) return null
  if (date.getFullYear() !== year || date.getMonth() !== month || date.getDate() !== day) return null
  return date
}

const formatDateInput = (value) => {
  const digits = (value || '').replace(/\D/g, '').slice(0, 8)
  if (digits.length <= 2) return digits
  if (digits.length <= 4) {
    return `${digits.slice(0, 2)}/${digits.slice(2)}`
  }
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`
}

const formatLocalISO = (date) => {
  if (!date) return null
  const pad = (value) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:00`
}

const buildLocalISO = (dateStr, timeStr) => {
  const base = parseDateBR(dateStr)
  if (!base) return null
  const time = timeStr && timeStr.length ? timeStr : '08:00'
  const [hh, mm] = time.split(':').map(Number)
  base.setHours(hh || 0, mm || 0, 0, 0)
  return formatLocalISO(base)
}

const buildEndISO = (dateStr, startTime, endTime) => {
  if (!endTime) return null
  const startDate = parseDateBR(dateStr)
  const endDate = parseDateBR(dateStr)
  if (!startDate || !endDate) return null
  const startParts = (startTime && startTime.length ? startTime : '08:00').split(':').map(Number)
  const endParts = endTime.split(':').map(Number)
  startDate.setHours(startParts[0] || 0, startParts[1] || 0, 0, 0)
  endDate.setHours(endParts[0] || 0, endParts[1] || 0, 0, 0)
  if (endDate <= startDate) {
    endDate.setDate(endDate.getDate() + 1)
  }
  return formatLocalISO(endDate)
}

const capitalize = (value) => {
  if (!value) return ''
  const str = value.toString().toLowerCase()
  return str.charAt(0).toUpperCase() + str.slice(1)
}

export default function Agenda() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('dashboardSidebar') === '1')
  const [snapshot, setSnapshot] = useState({
    summary: emptySummary,
    upcomingEvents: [],
    typeSummary: [],
    waitlistCount: 0,
  })
  const [activeTypes, setActiveTypes] = useState(() => TYPE_OPTIONS.map((item) => item.value))
  const [searchInput, setSearchInput] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [calendarLoading, setCalendarLoading] = useState(false)
  const [periodLabel, setPeriodLabel] = useState('Semana atual')
  const [activeView, setActiveView] = useState('timeGridWeek')
  const [showAddModal, setShowAddModal] = useState(false)
  const [addForm, setAddForm] = useState(emptyEventForm)
  const [addError, setAddError] = useState('')
  const [addSubmitting, setAddSubmitting] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [editForm, setEditForm] = useState(emptyEventForm)
  const [editError, setEditError] = useState('')
  const [editSubmitting, setEditSubmitting] = useState(false)
  const [showUpcomingModal, setShowUpcomingModal] = useState(false)
  const [showWaitlistModal, setShowWaitlistModal] = useState(false)
  const [waitlistItems, setWaitlistItems] = useState([])
  const [waitlistForm, setWaitlistForm] = useState(emptyWaitlistForm)
  const [waitlistError, setWaitlistError] = useState('')
  const [waitlistLoading, setWaitlistLoading] = useState(false)

  const calendarRef = useRef(null)
  const calendarInstanceRef = useRef(null)
  const filterRef = useRef({ types: activeTypes, search: '' })
  const addReminderRef = useRef(true)
  const editReminderRef = useRef(true)

  const typeCounts = useMemo(() => {
    const counts = {}
    let total = 0
    snapshot.typeSummary.forEach((item) => {
      const value = item?.slug || ''
      const count = Number(item?.count) || 0
      if (value) {
        counts[value] = count
      }
      total += count
    })
    return { counts, total }
  }, [snapshot.typeSummary])

  const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/agenda'
  const sidebarNav = useMemo(() => navItems, [])

  const handleToggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next)
    localStorage.setItem('dashboardSidebar', next ? '1' : '0')
    setTimeout(() => calendarInstanceRef.current?.updateSize(), 260)
  }

  const refreshSnapshot = useCallback(async () => {
    try {
      const response = await fetch('/api/agenda_snapshot', { credentials: 'same-origin' })
      if (!response.ok) return
      const data = await response.json()
      setSnapshot({
        summary: data.summary || emptySummary,
        upcomingEvents: data.upcoming_events || [],
        typeSummary: data.type_summary || [],
        waitlistCount: data.waitlist_count ?? 0,
      })
    } catch (error) {
      // silencioso
    }
  }, [])

  const openAddModal = useCallback((prefill = {}) => {
    setAddForm({ ...emptyEventForm, ...prefill })
    addReminderRef.current = typeof prefill.sendReminders === 'boolean' ? prefill.sendReminders : true
    setAddError('')
    setShowAddModal(true)
  }, [])

  const openEditModal = useCallback((prefill) => {
    setEditForm({ ...emptyEventForm, ...prefill })
    editReminderRef.current = Boolean(prefill?.sendReminders)
    setEditError('')
    setShowEditModal(true)
  }, [])

  useEffect(() => {
    const timeout = setTimeout(() => {
      setSearchTerm(searchInput.trim())
    }, 250)
    return () => clearTimeout(timeout)
  }, [searchInput])

  useEffect(() => {
    filterRef.current = { types: activeTypes, search: searchTerm }
    if (calendarInstanceRef.current) {
      calendarInstanceRef.current.refetchEvents()
    }
  }, [activeTypes, searchTerm])

  useEffect(() => {
    refreshSnapshot()
  }, [refreshSnapshot])

  useEffect(() => {
    if (!showWaitlistModal) return
    const loadWaitlist = async () => {
      setWaitlistLoading(true)
      setWaitlistError('')
      try {
        const response = await fetch('/api/waitlist', { credentials: 'same-origin' })
        const data = await response.json().catch(() => ({}))
        if (response.ok && Array.isArray(data.items)) {
          setWaitlistItems(data.items)
        } else {
          setWaitlistItems([])
        }
      } catch (error) {
        setWaitlistItems([])
      } finally {
        setWaitlistLoading(false)
      }
    }

    loadWaitlist()
  }, [showWaitlistModal])

  useEffect(() => {
    let active = true
    loadFullCalendar()
      .then((FullCalendar) => {
        if (!active || !calendarRef.current) return
        const calendar = new FullCalendar.Calendar(calendarRef.current, {
          timeZone: 'local',
          initialView: 'timeGridWeek',
          locale: 'pt-br',
          headerToolbar: false,
          nowIndicator: true,
          slotMinTime: '07:00:00',
          slotMaxTime: '19:00:00',
          slotDuration: '00:15:00',
          expandRows: true,
          dayMaxEventRows: 3,
          stickyHeaderDates: true,
          longPressDelay: 250,
          eventLongPressDelay: 250,
          selectLongPressDelay: 250,
          height: 'auto',
          handleWindowResize: true,
          selectable: true,
          selectMirror: true,
          editable: true,
          eventStartEditable: true,
          eventDurationEditable: true,
          dragScroll: true,
          events: {
            url: '/api/events',
            extraParams: () => ({
              types: filterRef.current.types.join(','),
              search: filterRef.current.search,
            }),
          },
          loading: (isLoading) => setCalendarLoading(isLoading),
          eventTimeFormat: { hour: '2-digit', minute: '2-digit', hour12: false },
          dayHeaderFormat: { weekday: 'short', day: '2-digit', month: '2-digit' },
          select: (info) => {
            const start = info.start
            const end = info.end
            const timeStr = `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(
              2,
              '0',
            )}`
            const endStr = end
              ? `${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`
              : ''
            openAddModal({
              date: formatDateBR(start),
              time: timeStr,
              endTime: endStr,
            })
            calendar.unselect()
          },
          eventClick: (info) => {
            const ev = info.event
            if (ev.classNames.includes('holiday-event')) return
            if (!ev.id) return
            const start = ev.start
            const end = ev.end || null
            openEditModal({
              id: ev.id,
              title: ev.title || '',
              phone: ev.extendedProps?.phone || '',
              date: start ? formatDateBR(start) : '',
              time: start
                ? `${String(start.getHours()).padStart(2, '0')}:${String(start.getMinutes()).padStart(2, '0')}`
                : '',
              endTime: end
                ? `${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`
                : '',
              notes: ev.extendedProps?.notes || '',
              type: (ev.extendedProps?.type || 'consulta').toLowerCase(),
              billing: (ev.extendedProps?.billing || 'particular').toLowerCase(),
              insurer: ev.extendedProps?.insurer || '',
              sendReminders: Boolean(ev.extendedProps?.send_reminders),
            })
          },
          eventDrop: async (info) => {
            const ev = info.event
            if (ev.classNames.includes('holiday-event') || !ev.id) {
              info.revert()
              return
            }
            try {
              const payload = {
                start: ev.start ? formatLocalISO(ev.start) : null,
                end: ev.end ? formatLocalISO(ev.end) : null,
              }
              const response = await fetch(`/api/events/${encodeURIComponent(ev.id)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload),
              })
              const data = await response.json().catch(() => ({}))
              if (!response.ok || !data.success) {
                info.revert()
                window.alert('Não foi possível atualizar o evento.')
              } else {
                refreshSnapshot()
              }
            } catch (error) {
              info.revert()
              window.alert('Falha de rede ao atualizar o evento.')
            }
          },
          eventResize: async (info) => {
            const ev = info.event
            if (ev.classNames.includes('holiday-event') || !ev.id) {
              info.revert()
              return
            }
            try {
              const payload = {
                start: ev.start ? formatLocalISO(ev.start) : null,
                end: ev.end ? formatLocalISO(ev.end) : null,
              }
              const response = await fetch(`/api/events/${encodeURIComponent(ev.id)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload),
              })
              const data = await response.json().catch(() => ({}))
              if (!response.ok || !data.success) {
                info.revert()
                window.alert('Não foi possível atualizar o evento.')
              } else {
                refreshSnapshot()
              }
            } catch (error) {
              info.revert()
              window.alert('Falha de rede ao atualizar o evento.')
            }
          },
          eventContent: (arg) => {
            const wrapper = document.createElement('div')
            wrapper.className = 'event-chip'
            const title = document.createElement('div')
            title.className = 'event-chip__title'
            title.textContent = arg.event.title || 'Evento'
            wrapper.appendChild(title)

            const meta = document.createElement('div')
            meta.className = 'event-chip__meta'
            const type = (arg.event.extendedProps?.type || '').toLowerCase()
            const billing = arg.event.extendedProps?.billing || ''
            const pieces = []
            if (arg.view.type === 'dayGridMonth' && arg.timeText) {
              pieces.push(arg.timeText)
            }
            if (TYPE_LABELS[type]) {
              pieces.push(TYPE_LABELS[type])
            }
            if (billing) {
              pieces.push(capitalize(billing))
            }
            meta.textContent = pieces.join(' · ')
            if (meta.textContent) {
              wrapper.appendChild(meta)
            }
            return { domNodes: [wrapper] }
          },
          eventDidMount: (info) => {
            const type = (info.event.extendedProps?.type || '').toLowerCase()
            const color = EVENT_COLORS[type] || '#131d35'
            info.el.style.setProperty('--event-accent', color)
          },
          datesSet: (info) => {
            const view = info.view
            const start = view.currentStart
            const end = new Date(view.currentEnd.getTime() - 24 * 60 * 60 * 1000)
            if (view.type === 'timeGridWeek') {
              const startStr = start.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
              const endStr = end.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
              setPeriodLabel(`${startStr} a ${endStr}`)
            } else if (view.type === 'dayGridMonth') {
              setPeriodLabel(
                start.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' }),
              )
            } else {
              setPeriodLabel(
                start.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' }),
              )
            }
            setActiveView(view.type)
          },
        })
        calendar.render()
        calendarInstanceRef.current = calendar
      })
      .catch(() => {})

    return () => {
      active = false
      if (calendarInstanceRef.current) {
        calendarInstanceRef.current.destroy()
        calendarInstanceRef.current = null
      }
    }
  }, [openAddModal, openEditModal, refreshSnapshot])

  useEffect(() => {
    if (!showAddModal && !showEditModal && !showUpcomingModal && !showWaitlistModal) return
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setShowAddModal(false)
        setShowEditModal(false)
        setShowUpcomingModal(false)
        setShowWaitlistModal(false)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [showAddModal, showEditModal, showUpcomingModal, showWaitlistModal])

  const handleToggleType = (type) => {
    setActiveTypes((prev) => {
      const next = prev.includes(type) ? prev.filter((item) => item !== type) : [...prev, type]
      if (!next.length) {
        return TYPE_OPTIONS.map((item) => item.value)
      }
      return TYPE_OPTIONS.map((item) => item.value).filter((value) => next.includes(value))
    })
  }

  const handleChangeAddType = (value) => {
    setAddForm((prev) => {
      if (value === 'bloqueio') {
        addReminderRef.current = prev.sendReminders
        return { ...prev, type: value, sendReminders: false }
      }
      const nextReminders = prev.type === 'bloqueio' ? addReminderRef.current : prev.sendReminders
      return { ...prev, type: value, sendReminders: nextReminders }
    })
  }

  const handleChangeEditType = (value) => {
    setEditForm((prev) => {
      if (value === 'bloqueio') {
        editReminderRef.current = prev.sendReminders
        return { ...prev, type: value, sendReminders: false }
      }
      const nextReminders = prev.type === 'bloqueio' ? editReminderRef.current : prev.sendReminders
      return { ...prev, type: value, sendReminders: nextReminders }
    })
  }


  const handleAddSubmit = async (event) => {
    event.preventDefault()
    setAddError('')
    if (!addForm.title.trim() || !addForm.phone.trim() || !addForm.date.trim()) {
      setAddError('Preencha o nome, telefone e a data.')
      return
    }
    const startISO = buildLocalISO(addForm.date, addForm.time)
    const endISO = buildEndISO(addForm.date, addForm.time, addForm.endTime)
    setAddSubmitting(true)
    try {
      const payload = {
        title: addForm.title.trim(),
        phone: addForm.phone.trim(),
        start: startISO,
        end: endISO,
        notes: addForm.notes,
        type: addForm.type,
        billing: addForm.billing,
        insurer: addForm.insurer.trim(),
        send_reminders: addForm.type !== 'bloqueio' && addForm.sendReminders,
      }
      const response = await fetch('/api/add_event', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Erro ao salvar')
      }
      setShowAddModal(false)
      setAddForm(emptyEventForm)
      calendarInstanceRef.current?.refetchEvents()
      await refreshSnapshot()
    } catch (error) {
      setAddError(error.message || 'Não foi possível salvar o agendamento.')
    } finally {
      setAddSubmitting(false)
    }
  }

  const handleEditSubmit = async (event) => {
    event.preventDefault()
    setEditError('')
    if (!editForm.id) {
      setEditError('Evento inválido.')
      return
    }
    if (!editForm.title.trim() || !editForm.phone.trim() || !editForm.date.trim()) {
      setEditError('Preencha o nome, telefone e a data.')
      return
    }
    const startISO = buildLocalISO(editForm.date, editForm.time)
    const endISO = buildEndISO(editForm.date, editForm.time, editForm.endTime)
    setEditSubmitting(true)
    try {
      const payload = {
        title: editForm.title.trim(),
        phone: editForm.phone.trim(),
        start: startISO,
        end: endISO,
        notes: editForm.notes,
        type: editForm.type,
        billing: editForm.billing,
        insurer: editForm.insurer.trim(),
        send_reminders: editForm.type !== 'bloqueio' && editForm.sendReminders,
      }
      const response = await fetch(`/api/events/${encodeURIComponent(editForm.id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Erro ao salvar')
      }
      setShowEditModal(false)
      calendarInstanceRef.current?.refetchEvents()
      await refreshSnapshot()
    } catch (error) {
      setEditError(error.message || 'Não foi possível salvar o agendamento.')
    } finally {
      setEditSubmitting(false)
    }
  }

  const handleDeleteEvent = async () => {
    if (!editForm.id) return
    if (!window.confirm('Deseja realmente excluir este agendamento?')) return
    try {
      const response = await fetch(`/api/events/${encodeURIComponent(editForm.id)}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Erro ao excluir')
      }
      setShowEditModal(false)
      calendarInstanceRef.current?.refetchEvents()
      await refreshSnapshot()
    } catch (error) {
      window.alert(error.message || 'Não foi possível excluir o agendamento.')
    }
  }

  const handleAddWaitlist = async () => {
    setWaitlistError('')
    if (!waitlistForm.name.trim()) {
      setWaitlistError('Informe o nome do paciente.')
      return
    }
    try {
      const response = await fetch('/api/waitlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          name: waitlistForm.name.trim(),
          billing: waitlistForm.billing,
          email: waitlistForm.email.trim(),
          phone1: waitlistForm.phone1.trim(),
          phone2: waitlistForm.phone2.trim(),
          notes: waitlistForm.notes.trim(),
        }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Erro ao adicionar')
      }
      setWaitlistForm(emptyWaitlistForm)
      const responseList = await fetch('/api/waitlist', { credentials: 'same-origin' })
      const listData = await responseList.json().catch(() => ({}))
      setWaitlistItems(Array.isArray(listData.items) ? listData.items : [])
      await refreshSnapshot()
    } catch (error) {
      setWaitlistError(error.message || 'Não foi possível adicionar.')
    }
  }

  const handleRemoveWaitlist = async (id) => {
    if (!window.confirm('Remover paciente da lista de espera?')) return
    try {
      const response = await fetch(`/api/waitlist/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.success) {
        throw new Error('Erro ao remover')
      }
      setWaitlistItems((prev) => prev.filter((item) => item.id !== id))
      await refreshSnapshot()
    } catch (error) {
      window.alert('Não foi possível remover o paciente.')
    }
  }

  return (
    <div className={`dashboard-shell agenda-shell ${collapsed ? 'is-collapsed' : ''}`}>
      <aside className="dashboard-sidebar">
        <div className="dashboard-sidebar__brand">
          
          <div className="dashboard-logo-wrap">
            <img src="/static/images/5.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--full" />
            <img src="/static/images/15.svg" alt="Ponza Health" className="dashboard-logo dashboard-logo--compact" />
          </div>
          <div className="dashboard-title"></div>
          <button className="dashboard-toggle" type="button" onClick={handleToggleSidebar} aria-label="Alternar menu">
            <i className="fa fa-bars" />
          </button>
        </div>
        <nav className="dashboard-nav" aria-label="Menu principal">
          {sidebarNav.map((item) => (
            <a
              key={item.href}
              className={`dashboard-link ${currentPath === resolvePath(item.href) ? 'is-active' : ''}`}
              href={item.href}
            >
              <i className={`fa ${item.icon}`} aria-hidden="true" />
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="dashboard-sidebar__footer">
          <a className="dashboard-link is-logout" href={withBackend('/logout')}>
            <i className="fa fa-sign-out" aria-hidden="true" />
            <span>Sair</span>
          </a>
        </div>
      </aside>

      <main className="dashboard-main">
        <header className="dashboard-header">
          <div>
            <p className="dashboard-kicker">Agenda</p>
            <h1>Coordene seu dia com clareza</h1>
          </div>
          <div className="dashboard-actions">
            <a className="dashboard-icon-btn" href="/account" aria-label="Minha conta">
              <i className="fa fa-user" aria-hidden="true" />
            </a>
            <button className="dashboard-icon-btn" type="button" aria-label="Notificações">
              <i className="fa fa-bell" aria-hidden="true" />
            </button>
          </div>
        </header>
        <div className="agenda-actions-bar">
          <div className="agenda-actions-bar__meta">
            Hoje <strong>{snapshot.summary.today_count}</strong> · Próximos 7 dias{' '}
            <strong>{snapshot.summary.upcoming_count}</strong> · Lista de espera{' '}
            <strong>{snapshot.waitlistCount}</strong>
          </div>
          <div className="agenda-actions-bar__buttons">
            <button className="btn-primary" type="button" onClick={() => openAddModal()}>
              Novo agendamento
            </button>
            <button className="btn-outline" type="button" onClick={() => setShowUpcomingModal(true)}>
              Próximos 7 dias
            </button>
            <button className="btn-outline" type="button" onClick={() => setShowWaitlistModal(true)}>
              Lista de espera
            </button>
          </div>
        </div>

        <section className="agenda-summary">
          <article className="agenda-summary-card">
            <div className="agenda-summary-icon">
              <i className="fa fa-calendar-check-o" aria-hidden="true" />
            </div>
            <div>
              <span>Hoje</span>
              <strong>{snapshot.summary.today_count}</strong>
              <small>Consultas confirmadas</small>
            </div>
          </article>
          <article className="agenda-summary-card">
            <div className="agenda-summary-icon is-green">
              <i className="fa fa-calendar" aria-hidden="true" />
            </div>
            <div>
              <span>Semana</span>
              <strong>{snapshot.summary.week_count}</strong>
              <small>Compromissos na semana</small>
            </div>
          </article>
          <article className="agenda-summary-card">
            <div className="agenda-summary-icon is-purple">
              <i className="fa fa-refresh" aria-hidden="true" />
            </div>
            <div>
              <span>Retornos</span>
              <strong>{snapshot.summary.returns_count}</strong>
              <small>Retornos planejados</small>
            </div>
          </article>
          <article className="agenda-summary-card">
            <div className="agenda-summary-icon is-orange">
              <i className="fa fa-ban" aria-hidden="true" />
            </div>
            <div>
              <span>Bloqueios</span>
              <strong>{snapshot.summary.blocked_count}</strong>
              <small>Períodos reservados</small>
            </div>
          </article>
        </section>

        <section className={`agenda-calendar ${calendarLoading ? 'is-loading' : ''}`}>
          <div className="agenda-toolbar">
            <div className="agenda-toolbar__group">
              <button
                className="agenda-icon-btn"
                type="button"
                aria-label="Período anterior"
                onClick={() => calendarInstanceRef.current?.prev()}
              >
                <i className="fa fa-chevron-left" aria-hidden="true" />
              </button>
              <button
                className="btn-ghost"
                type="button"
                onClick={() => calendarInstanceRef.current?.today()}
              >
                Hoje
              </button>
              <button
                className="agenda-icon-btn"
                type="button"
                aria-label="Próximo período"
                onClick={() => calendarInstanceRef.current?.next()}
              >
                <i className="fa fa-chevron-right" aria-hidden="true" />
              </button>
            </div>
            <h3>{periodLabel}</h3>
            <div className="agenda-toolbar__group agenda-view-switch">
              <button
                className={`btn-outline agenda-view-toggle ${activeView === 'dayGridMonth' ? 'is-active' : ''}`}
                type="button"
                onClick={() => calendarInstanceRef.current?.changeView('dayGridMonth')}
              >
                Mês
              </button>
              <button
                className={`btn-outline agenda-view-toggle ${activeView === 'timeGridWeek' ? 'is-active' : ''}`}
                type="button"
                onClick={() => calendarInstanceRef.current?.changeView('timeGridWeek')}
              >
                Semana
              </button>
            </div>
          </div>

          <div className="agenda-filters data-table--controls">
            <div className="data-table__tools">
              <label className="data-table__search">
                <i className="fa fa-search" aria-hidden="true" />
                <input
                  type="search"
                  placeholder="Buscar por paciente, convênio ou observação"
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                />
              </label>
              <div className="data-table__filters" role="group" aria-label="Tipos de agendamento">
                {TYPE_OPTIONS.map((item) => (
                  <button
                    key={item.value}
                    className={`filter-chip ${activeTypes.includes(item.value) ? 'is-active' : ''}`}
                    type="button"
                    onClick={() => handleToggleType(item.value)}
                  >
                    {item.label}
                    <span className="filter-chip__count">{typeCounts.counts[item.value] || 0}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div ref={calendarRef} className="agenda-calendar__body" />
        </section>

      </main>

      {showAddModal ? (
        <div
          className="dashboard-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Novo agendamento"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setShowAddModal(false)
            }
          }}
        >
          <div className="dashboard-modal__card dashboard-modal__card--tight">
            <div className="dashboard-modal__header dashboard-modal__header--borderless">
              <div>
                <p className="dashboard-kicker">Agenda</p>
                <h3>Novo agendamento</h3>
              </div>
              <button className="icon-button" type="button" onClick={() => setShowAddModal(false)} aria-label="Fechar">
                <i className="fa fa-times" aria-hidden="true" />
              </button>
            </div>
            <form className="dashboard-form" onSubmit={handleAddSubmit}>
              <div className="dashboard-form__row">
                <label>
                  Paciente
                  <input
                    type="text"
                    value={addForm.title}
                    onChange={(event) => setAddForm((prev) => ({ ...prev, title: event.target.value }))}
                    placeholder="Nome do paciente"
                    required
                  />
                </label>
                <label>
                  Telefone do paciente
                  <input
                    type="tel"
                    value={addForm.phone}
                    onChange={(event) => setAddForm((prev) => ({ ...prev, phone: event.target.value }))}
                    placeholder="(__) _____-____"
                    required
                  />
                </label>
              </div>
              <div className="toggle-center">
                <label className={`toggle-control ${addForm.type === 'bloqueio' ? 'is-disabled' : ''}`}>
                  <span className="toggle-label">Receber lembretes por WhatsApp</span>
                  <input
                    type="checkbox"
                    checked={addForm.sendReminders}
                    onChange={(event) =>
                      setAddForm((prev) => ({ ...prev, sendReminders: event.target.checked }))
                    }
                    disabled={addForm.type === 'bloqueio'}
                  />
                  <span className="toggle-track">
                    <span className="toggle-thumb" />
                  </span>
                </label>
                <p className="dashboard-form__hint">
                  Pacientes recebem um lembrete ao criar a consulta e 60 minutos antes do horário agendado.
                </p>
              </div>
              <div className="dashboard-form__row">
                <label>
                  Data
                  <input
                    type="text"
                    placeholder="dd/mm/aaaa"
                    inputMode="numeric"
                    value={addForm.date}
                    onChange={(event) =>
                      setAddForm((prev) => ({ ...prev, date: formatDateInput(event.target.value) }))
                    }
                    required
                  />
                </label>
                <label>
                  Horário
                  <input
                    type="time"
                    value={addForm.time}
                    onChange={(event) => setAddForm((prev) => ({ ...prev, time: event.target.value }))}
                  />
                </label>
              </div>
              <div className="dashboard-form__row">
                <label>
                  Término
                  <input
                    type="time"
                    value={addForm.endTime}
                    onChange={(event) => setAddForm((prev) => ({ ...prev, endTime: event.target.value }))}
                  />
                </label>
                <label>
                  Tipo
                  <select
                    value={addForm.type}
                    onChange={(event) => handleChangeAddType(event.target.value)}
                  >
                    <option value="consulta">Consulta</option>
                    <option value="retorno">Retorno</option>
                    <option value="procedimento">Procedimento</option>
                    <option value="bloqueio">Bloqueio</option>
                  </select>
                </label>
              </div>
              <div className="dashboard-form__row">
                <label>
                  Pagamento
                  <select
                    value={addForm.billing}
                    onChange={(event) => setAddForm((prev) => ({ ...prev, billing: event.target.value }))}
                  >
                    <option value="particular">Particular</option>
                    <option value="convenio">Convênio</option>
                  </select>
                </label>
                {addForm.billing === 'convenio' ? (
                  <label>
                    Convênio
                    <input
                      type="text"
                      value={addForm.insurer}
                      onChange={(event) => setAddForm((prev) => ({ ...prev, insurer: event.target.value }))}
                      placeholder="Nome do convênio"
                    />
                  </label>
                ) : null}
              </div>
              <label>
                Observações
                <textarea
                  rows="3"
                  value={addForm.notes}
                  onChange={(event) => setAddForm((prev) => ({ ...prev, notes: event.target.value }))}
                  placeholder="Observações adicionais"
                />
              </label>
              {addError ? <div className="dashboard-form__error">{addError}</div> : null}
              <div className="dashboard-form__actions dashboard-form__actions--centered">
                <button className="btn-primary btn-small modal-action-btn" type="submit" disabled={addSubmitting}>
                  {addSubmitting ? 'Salvando...' : 'Agendar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {showEditModal ? (
        <div
          className="dashboard-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Editar agendamento"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setShowEditModal(false)
            }
          }}
        >
          <div className="dashboard-modal__card">
            <div className="dashboard-modal__header">
              <div>
                <p className="dashboard-kicker">Agenda</p>
                <h3>Editar agendamento</h3>
                <p className="dashboard-subtitle">Atualize dados do atendimento ou ajuste horários.</p>
              </div>
              <button className="icon-button" type="button" onClick={() => setShowEditModal(false)} aria-label="Fechar">
                <i className="fa fa-times" aria-hidden="true" />
              </button>
            </div>
            <form className="dashboard-form" onSubmit={handleEditSubmit}>
              <label>
                Paciente
                <input
                  type="text"
                  value={editForm.title}
                  onChange={(event) => setEditForm((prev) => ({ ...prev, title: event.target.value }))}
                  required
                />
              </label>
              <label>
                Telefone do paciente
                <input
                  type="tel"
                  value={editForm.phone}
                  onChange={(event) => setEditForm((prev) => ({ ...prev, phone: event.target.value }))}
                  required
                />
              </label>
              <div className="toggle-center">
                <label className={`toggle-control ${editForm.type === 'bloqueio' ? 'is-disabled' : ''}`}>
                  <span className="toggle-label">Receber lembretes por WhatsApp</span>
                  <input
                    type="checkbox"
                    checked={editForm.sendReminders}
                    onChange={(event) =>
                      setEditForm((prev) => ({ ...prev, sendReminders: event.target.checked }))
                    }
                    disabled={editForm.type === 'bloqueio'}
                  />
                  <span className="toggle-track">
                    <span className="toggle-thumb" />
                  </span>
                </label>
                <p className="dashboard-form__hint">
                  Pacientes recebem um lembrete ao criar a consulta e 60 minutos antes do horário agendado.
                </p>
              </div>
              <div className="dashboard-form__row">
                <label>
                  Data
                  <input
                    type="text"
                    placeholder="dd/mm/aaaa"
                    inputMode="numeric"
                    value={editForm.date}
                    onChange={(event) =>
                      setEditForm((prev) => ({ ...prev, date: formatDateInput(event.target.value) }))
                    }
                    required
                  />
                </label>
                <label>
                  Horário
                  <input
                    type="time"
                    value={editForm.time}
                    onChange={(event) => setEditForm((prev) => ({ ...prev, time: event.target.value }))}
                  />
                </label>
              </div>
              <div className="dashboard-form__row">
                <label>
                  Término
                  <input
                    type="time"
                    value={editForm.endTime}
                    onChange={(event) => setEditForm((prev) => ({ ...prev, endTime: event.target.value }))}
                  />
                </label>
                <label>
                  Tipo
                  <select
                    value={editForm.type}
                    onChange={(event) => handleChangeEditType(event.target.value)}
                  >
                    <option value="consulta">Consulta</option>
                    <option value="retorno">Retorno</option>
                    <option value="procedimento">Procedimento</option>
                    <option value="bloqueio">Bloqueio</option>
                  </select>
                </label>
              </div>
              <div className="dashboard-form__row">
                <label>
                  Pagamento
                  <select
                    value={editForm.billing}
                    onChange={(event) => setEditForm((prev) => ({ ...prev, billing: event.target.value }))}
                  >
                    <option value="particular">Particular</option>
                    <option value="convenio">Convênio</option>
                  </select>
                </label>
                {editForm.billing === 'convenio' ? (
                  <label>
                    Convênio
                    <input
                      type="text"
                      value={editForm.insurer}
                      onChange={(event) => setEditForm((prev) => ({ ...prev, insurer: event.target.value }))}
                      placeholder="Nome do convênio"
                    />
                  </label>
                ) : null}
              </div>
              <label>
                Observações
                <textarea
                  rows="3"
                  value={editForm.notes}
                  onChange={(event) => setEditForm((prev) => ({ ...prev, notes: event.target.value }))}
                />
              </label>
              {editError ? <div className="dashboard-form__error">{editError}</div> : null}
              <div className="dashboard-form__actions dashboard-form__actions--centered">
                <button className="btn-outline btn-danger btn-small" type="button" onClick={handleDeleteEvent}>
                  Excluir
                </button>
                <button className="btn-primary btn-small" type="submit" disabled={editSubmitting}>
                  {editSubmitting ? 'Salvando...' : 'Salvar alterações'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {showUpcomingModal ? (
        <div
          className="dashboard-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Próximos agendamentos"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setShowUpcomingModal(false)
            }
          }}
        >
          <div
            className="dashboard-modal__card dashboard-modal__card--wide dashboard-modal__card--tight"
            style={{ width: '1100px', maxWidth: '100%' }}
          >
            <div className="dashboard-modal__header">
              <div>
                <p className="dashboard-kicker">Agenda</p>
                <h3>Próximos agendamentos</h3>
                <p className="dashboard-subtitle">
                  {snapshot.summary.upcoming_count} compromissos nos próximos 7 dias.
                </p>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => setShowUpcomingModal(false)}
                aria-label="Fechar"
              >
                <i className="fa fa-times" aria-hidden="true" />
              </button>
            </div>
            <div className="data-table data-table--compact data-table--dashboard">
              <div className="agenda-upcoming-table">
                <table>
                  <thead>
                    <tr>
                      <th>Data</th>
                      <th>Horário</th>
                      <th>Paciente</th>
                      <th>Tipo</th>
                      <th>Pagamento</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.upcomingEvents.length ? (
                      snapshot.upcomingEvents.map((item) => {
                        const [datePart, timePart] = (item.start_label || '').split(' ')
                        return (
                          <tr key={item.id || item.start_iso}>
                            <td>
                              <div className="agenda-upcoming-date">
                                <strong>{datePart || '—'}</strong>
                                <span>{item.weekday || ''}</span>
                              </div>
                            </td>
                            <td>{timePart || '—'}</td>
                            <td>{item.title}</td>
                            <td>{item.type_label}</td>
                            <td>{item.billing_label || '—'}</td>
                          </tr>
                        )
                      })
                    ) : (
                      <tr>
                        <td colSpan="5" className="empty-cell">
                          Nenhum agendamento futuro registrado.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {showWaitlistModal ? (
        <div
          className="dashboard-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Lista de espera"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setShowWaitlistModal(false)
            }
          }}
        >
          <div className="dashboard-modal__card dashboard-modal__card--wide dashboard-modal__card--waitlist">
            <div className="dashboard-modal__header dashboard-modal__header--borderless">
              <div>
                <p className="dashboard-kicker">Agenda</p>
                <h3>Lista de espera</h3>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => setShowWaitlistModal(false)}
                aria-label="Fechar"
              >
                <i className="fa fa-times" aria-hidden="true" />
              </button>
            </div>
            <div className="waitlist-grid">
              <div className="waitlist-panel">
                <h4>Na lista</h4>
                {waitlistLoading ? <div className="agenda-empty">Carregando...</div> : null}
                <div className="waitlist-items">
                  {!waitlistLoading && !waitlistItems.length ? (
                    <div className="agenda-empty">Nenhum paciente na lista de espera.</div>
                  ) : null}
                  {waitlistItems.map((item) => (
                    <div className="waitlist-item" key={item.id}>
                      <div>
                        <strong>{item.name || 'Sem nome'}</strong>
                        <small>
                          {item.billing || 'Particular'}
                          {item.email ? ` · ${item.email}` : ''}
                        </small>
                        <small>{[item.phone1, item.phone2].filter(Boolean).join(' · ')}</small>
                        {item.notes ? <small>{item.notes}</small> : null}
                      </div>
                      <div className="waitlist-actions">
                        <button
                          className="icon-button is-danger"
                          type="button"
                          aria-label="Remover"
                          onClick={() => handleRemoveWaitlist(item.id)}
                        >
                          <i className="fa fa-trash" aria-hidden="true" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="waitlist-panel">
                <h4>Novo paciente</h4>
                <form className="dashboard-form" onSubmit={(event) => event.preventDefault()}>
                  <label>
                    Paciente
                    <input
                      type="text"
                      value={waitlistForm.name}
                      onChange={(event) => setWaitlistForm((prev) => ({ ...prev, name: event.target.value }))}
                      placeholder="Nome do paciente"
                    />
                  </label>
                  <label>
                    Convênio
                    <select
                      value={waitlistForm.billing}
                      onChange={(event) => setWaitlistForm((prev) => ({ ...prev, billing: event.target.value }))}
                    >
                      <option value="Particular">Particular</option>
                      <option value="Convênio">Convênio</option>
                    </select>
                  </label>
                  <label>
                    E-mail
                    <input
                      type="email"
                      value={waitlistForm.email}
                      onChange={(event) => setWaitlistForm((prev) => ({ ...prev, email: event.target.value }))}
                      placeholder="email@exemplo.com"
                    />
                  </label>
                  <div className="dashboard-form__row">
                    <label>
                      Tel. celular
                      <input
                        type="tel"
                        value={waitlistForm.phone1}
                        onChange={(event) => setWaitlistForm((prev) => ({ ...prev, phone1: event.target.value }))}
                        placeholder="(__) _____-____"
                      />
                    </label>
                  </div>
                  <label>
                    Observação
                    <input
                      type="text"
                      value={waitlistForm.notes}
                      onChange={(event) => setWaitlistForm((prev) => ({ ...prev, notes: event.target.value }))}
                    />
                  </label>
                  {waitlistError ? <div className="dashboard-form__error">{waitlistError}</div> : null}
                  <button className="btn-primary btn-block modal-action-btn" type="button" onClick={handleAddWaitlist}>
                    Adicionar paciente
                  </button>
                </form>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
