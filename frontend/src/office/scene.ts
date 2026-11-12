/**
 * The assistants' office: a small corporate floor drawn with three.js.
 *
 * Layout (metres, x to the right, z towards the viewer):
 *   left   two rows of desks either side of a central aisle (z = AISLE)
 *   top right   glass meeting room
 *   bottom right   lounge: pool table, coffee counter, sofa
 *
 * Each assistant is a little figure driven by a state machine. The floor runs a loop of
 * work -> meeting -> work -> break; who joins what is picked afresh each time, people set
 * off a few seconds apart and walk at their own pace, so it never looks drilled.
 */
import * as THREE from 'three'

export type AgentInfo = { key: string; name: string; color: string; built: boolean }
export type Status = Record<string, string>

type Pose = 'type' | 'sit' | 'pool' | 'coffee' | 'sofa'
type Spot = { pos: [number, number]; face: number; accessX: number; via: [number, number][]; pose: Pose }

const AISLE = -1
const SKIN = ['#F1C9A5', '#D9A066', '#B9784F', '#8D5A3B', '#EBB58E', '#C68863', '#A0694A']
const PHASES = [
  { name: 'work', seconds: 22 },
  { name: 'meeting', seconds: 20 },
  { name: 'work', seconds: 20 },
  { name: 'break', seconds: 24 },
] as const

const DESKS: Spot[] = [
  ...[-10, -7.2, -4.4, -1.6].map((x): Spot => ({ pos: [x, -3.9], face: Math.PI, accessX: x, via: [], pose: 'type' })),
  ...[-10, -7.2, -4.4].map((x): Spot => ({ pos: [x, 1.9], face: 0, accessX: x, via: [], pose: 'type' })),
]
const DOOR: [number, number] = [4, -3.2]
const MEETING: Spot[] = [
  ...[5.6, 6.8, 8.0].map((x): Spot => ({ pos: [x, -4.0], face: Math.PI, accessX: 4, via: [DOOR], pose: 'sit' })),
  ...[5.6, 6.8, 8.0].map((x): Spot => ({ pos: [x, -6.4], face: 0, accessX: 4, via: [DOOR, [4.3, -6.6]], pose: 'sit' })),
]
const POOL: Spot[] = [
  { pos: [6.0, 3.25], face: 0, accessX: 6.0, via: [], pose: 'pool' },
  { pos: [7.4, 3.25], face: 0, accessX: 7.4, via: [], pose: 'pool' },
  { pos: [6.6, 6.0], face: Math.PI, accessX: 4.4, via: [[4.4, 6.0]], pose: 'pool' },
]
const COFFEE: Spot[] = [{ pos: [10.4, 1.4], face: Math.PI / 2, accessX: 10.4, via: [], pose: 'coffee' }]
const SOFA: Spot[] = [
  { pos: [10.65, 5.3], face: -Math.PI / 2, accessX: 9.2, via: [[9.2, 5.3]], pose: 'sofa' },
  { pos: [10.65, 6.5], face: -Math.PI / 2, accessX: 9.2, via: [[9.2, 6.5]], pose: 'sofa' },
]
const TABLE = { x: 6.5, z: 4.6, w: 2.8, d: 1.5, y: 0.86 }

const rand = (a: number, b: number) => a + Math.random() * (b - a)
const pick = <T,>(xs: T[], n: number): T[] => [...xs].sort(() => Math.random() - 0.5).slice(0, n)
const turnTowards = (from: number, to: number, amount: number) => {
  const diff = Math.atan2(Math.sin(to - from), Math.cos(to - from))
  return from + diff * Math.min(1, amount)
}

function mat(color: string, extra: THREE.MeshStandardMaterialParameters = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.85, ...extra })
}
function box(w: number, h: number, d: number, m: THREE.Material, x: number, y: number, z: number, shadow = true) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m)
  mesh.position.set(x, y, z)
  mesh.castShadow = shadow
  mesh.receiveShadow = true
  return mesh
}

function label(text: string): THREE.Sprite {
  const c = document.createElement('canvas')
  c.width = 320
  c.height = 80
  const g = c.getContext('2d')!
  g.font = '600 38px Inter, system-ui, sans-serif'
  const w = Math.min(300, g.measureText(text).width + 36)
  g.fillStyle = 'rgba(15,23,42,0.88)'
  g.beginPath()
  g.roundRect((320 - w) / 2, 12, w, 56, 16)
  g.fill()
  g.fillStyle = '#fff'
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  g.fillText(text, 160, 41, 280)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }))
  s.scale.set(2.6, 0.65, 1)
  s.renderOrder = 10
  return s
}

class Person {
  root = new THREE.Group()
  private body = new THREE.Group()
  private head: THREE.Mesh
  private armL = new THREE.Group()
  private armR = new THREE.Group()
  private legL = new THREE.Group()
  private legR = new THREE.Group()
  private cup: THREE.Mesh

  spot: Spot
  path: [number, number][] = []
  pose: Pose | 'walk' = 'type'
  goal = ''              // why they are walking, for the status line
  leaveAt = -1           // time to set off for `next`
  next: Spot | null = null
  speed = rand(1.5, 2.1)
  private phase = rand(0, 10)   // so no two people move in step
  stretchAt = rand(6, 16)
  private nodAt = rand(2, 6)
  cheerUntil = 0
  aimUntil = 0
  speaking = false
  lookAt: THREE.Vector3 | null = null

  constructor(public info: AgentInfo, index: number, spot: Spot) {
    this.spot = spot
    const shirt = mat(info.color)
    const skin = mat(SKIN[index % SKIN.length])
    const dark = mat('#1E293B')

    const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.21, 0.42, 4, 12), shirt)
    torso.position.y = 1.0
    this.head = new THREE.Mesh(new THREE.SphereGeometry(0.19, 20, 16), skin)
    this.head.position.y = 1.52
    for (const side of [-1, 1]) {
      const eye = new THREE.Mesh(new THREE.SphereGeometry(0.025, 8, 8), dark)
      eye.position.set(side * 0.07, 0.03, 0.17)
      this.head.add(eye)
    }
    const hair = new THREE.Mesh(new THREE.SphereGeometry(0.195, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2.2), dark)
    hair.position.y = 0.02
    hair.rotation.x = -0.25
    this.head.add(hair)

    const limb = (g: THREE.Group, x: number, y: number, r: number, len: number, m: THREE.Material) => {
      const mesh = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 4, 8), m)
      mesh.position.y = -len / 2 - r
      mesh.castShadow = true
      g.position.set(x, y, 0)
      g.add(mesh)
      this.body.add(g)
    }
    limb(this.armL, -0.27, 1.27, 0.06, 0.36, shirt)
    limb(this.armR, 0.27, 1.27, 0.06, 0.36, shirt)
    limb(this.legL, -0.1, 0.72, 0.075, 0.5, dark)
    limb(this.legR, 0.1, 0.72, 0.075, 0.5, dark)

    this.cup = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.035, 0.1, 10), mat('#ffffff'))
    this.cup.position.set(0, -0.5, 0.05)
    this.cup.visible = false
    this.armR.add(this.cup)

    torso.castShadow = true
    this.head.castShadow = true
    this.body.add(torso, this.head)
    const tag = label(info.name)
    tag.position.y = 2.3
    this.root.add(this.body, tag)
    this.root.position.set(spot.pos[0], 0, spot.pos[1])
    this.root.rotation.y = spot.face
  }

  /** Walk from the current spot to another, out to the aisle and back in. */
  goTo(target: Spot, goal: string) {
    if (target === this.spot && this.pose !== 'walk') return
    const out = [...this.spot.via].reverse()
    this.path = [...out, [this.spot.accessX, AISLE], [target.accessX, AISLE], ...target.via, target.pos]
    this.spot = target
    this.pose = 'walk'
    this.goal = goal
    this.cup.visible = false
  }

  update(t: number, dt: number) {
    const p = this.root.position
    const w = t * 1 + this.phase
    let armL = 0, armR = 0, legL = 0, legR = 0, lean = 0, y = 0, headYaw = 0, headPitch = 0, spread = 0

    if (this.pose === 'walk') {
      const [tx, tz] = this.path[0]
      const dx = tx - p.x, dz = tz - p.z
      const dist = Math.hypot(dx, dz)
      const step = this.speed * dt
      if (dist <= step) {
        p.x = tx
        p.z = tz
        this.path.shift()
        if (this.path.length === 0) this.pose = this.spot.pose
      } else {
        p.x += (dx / dist) * step
        p.z += (dz / dist) * step
        this.root.rotation.y = turnTowards(this.root.rotation.y, Math.atan2(dx, dz), dt * 9)
      }
      const stride = t * this.speed * 4.2 + this.phase
      legL = Math.sin(stride) * 0.6
      legR = -legL
      armL = -legL * 0.7
      armR = legL * 0.7
      y = Math.abs(Math.sin(stride)) * 0.035
    } else {
      this.root.rotation.y = turnTowards(this.root.rotation.y, this.spot.face, dt * 6)
      const breathing = Math.sin(w * 1.6) * 0.012
      if (this.pose === 'type') {
        y = -0.26
        legL = legR = -1.45
        const stretching = t > this.stretchAt && t < this.stretchAt + 2.4
        if (t > this.stretchAt + 2.4) this.stretchAt = t + rand(9, 22)
        if (stretching) {
          // lean back, arms up: the stretch everyone does after a long stare at the screen
          const k = Math.sin(((t - this.stretchAt) / 2.4) * Math.PI)
          armL = armR = -1.25 - k * 1.7
          spread = k * 0.5
          lean = -k * 0.22
          headPitch = -k * 0.3
        } else {
          armL = -1.25 + Math.sin(w * 13) * 0.05
          armR = -1.25 + Math.sin(w * 11 + 1) * 0.05
          lean = 0.08 + breathing
          headPitch = 0.12 + Math.sin(w * 0.7) * 0.05
          headYaw = Math.sin(w * 0.23) * 0.12
        }
      } else if (this.pose === 'sit') {
        y = -0.26
        legL = legR = -1.45
        armL = armR = -0.9
        lean = 0.05 + breathing
        if (this.speaking) {
          armL = -1.0 + Math.sin(w * 3.1) * 0.35
          armR = -1.0 + Math.sin(w * 2.6 + 2) * 0.4
          spread = 0.15 + Math.sin(w * 1.7) * 0.1
          headYaw = Math.sin(w * 0.9) * 0.5        // looks round the table while talking
        } else {
          if (t > this.nodAt + 0.7) this.nodAt = t + rand(3, 8)
          if (t > this.nodAt) headPitch = Math.sin(((t - this.nodAt) / 0.7) * Math.PI * 2) * 0.16
        }
      } else if (this.pose === 'sofa') {
        y = -0.36
        legL = legR = -1.35
        lean = -0.28 + breathing
        armL = -0.5
        armR = -0.5
        spread = 0.35
        headYaw = Math.sin(w * 0.3) * 0.35
      } else if (this.pose === 'coffee') {
        this.cup.visible = true
        const sip = Math.max(0, Math.sin(w * 0.9))
        armR = -0.9 - sip * 1.1
        headPitch = -sip * 0.12
        lean = breathing
        legL = Math.sin(w * 0.4) * 0.04
      } else if (this.pose === 'pool') {
        if (t < this.aimUntil) {
          // bend over the table, cue arm slides back and forth
          lean = 0.75
          armL = -1.9
          armR = -0.7 + Math.sin(w * 6) * 0.25
          headPitch = -0.55
          legL = 0.25
        } else if (t < this.cheerUntil) {
          const k = Math.abs(Math.sin((this.cheerUntil - t) * 7))
          y = k * 0.16
          armL = armR = -2.7
          spread = 0.5
        } else {
          armL = Math.sin(w * 0.8) * 0.06
          armR = -0.5                               // resting a hand on the cue
          lean = breathing
          headPitch = 0.15
          legL = Math.sin(w * 0.35) * 0.05           // shifts weight while waiting
        }
      }
      if (this.lookAt && (this.pose === 'sit' || this.pose === 'pool') && !this.speaking && t >= this.aimUntil) {
        const want = Math.atan2(this.lookAt.x - p.x, this.lookAt.z - p.z) - this.root.rotation.y
        headYaw = THREE.MathUtils.clamp(Math.atan2(Math.sin(want), Math.cos(want)), -1.1, 1.1)
      }
    }

    const ease = Math.min(1, dt * 10)
    const to = (obj: THREE.Object3D, axis: 'x' | 'y' | 'z', v: number) => { obj.rotation[axis] += (v - obj.rotation[axis]) * ease }
    to(this.armL, 'x', armL); to(this.armR, 'x', armR)
    to(this.armL, 'z', -spread); to(this.armR, 'z', spread)
    to(this.legL, 'x', legL); to(this.legR, 'x', legR)
    to(this.body, 'x', lean)
    to(this.head, 'y', headYaw); to(this.head, 'x', headPitch)
    this.body.position.y += (y - this.body.position.y) * ease
  }
}

export class Office {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(32, 1, 0.1, 200)
  private people: Person[] = []
  private screens: THREE.MeshStandardMaterial[] = []
  private balls: { mesh: THREE.Mesh; v: THREE.Vector2 }[] = []
  private cueBall!: THREE.Mesh
  private cueTarget: THREE.Vector3 | null = null
  private clock = new THREE.Clock()
  private t = 0
  private phaseIndex = 0
  private phaseEnds = 6            // first meeting comes quickly so there is something to watch
  private speakerAt = 0
  private shotAt = 0
  private shooter = 0
  private angle = 0.35
  private raf = 0
  private paused = false
  private pending = 0
  private lastStatus = ''
  private disposed = false

  constructor(private canvas: HTMLCanvasElement, agents: AgentInfo[], private onStatus: (s: Status) => void) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap
    this.build()
    agents.forEach((a, i) => {
      const person = new Person(a, i, DESKS[i % DESKS.length])
      this.people.push(person)
      this.scene.add(person.root)
    })
    this.resize()
    this.frame()
    this.loop = this.loop.bind(this)
    this.raf = requestAnimationFrame(this.loop)
    document.addEventListener('visibilitychange', this.onVisibility)
  }

  // ---------- the floor ----------

  private build() {
    const s = this.scene
    s.add(new THREE.HemisphereLight('#ffffff', '#CBD5E1', 1.15))
    const sun = new THREE.DirectionalLight('#fff7ed', 1.6)
    sun.position.set(-8, 18, 10)
    sun.castShadow = true
    sun.shadow.mapSize.set(1024, 1024)
    Object.assign(sun.shadow.camera, { left: -16, right: 16, top: 12, bottom: -12, near: 1, far: 50 })
    sun.shadow.bias = -0.0005
    s.add(sun)

    const carpet = mat('#E6EAF1'), wall = mat('#F8FAFC'), wood = mat('#C9A77A'), white = mat('#FFFFFF')
    const dark = mat('#1E293B'), steel = mat('#94A3B8'), plantGreen = mat('#3F8F5B'), pot = mat('#B45309')

    const floor = box(24.6, 0.2, 16.6, carpet, 0, -0.1, 0, false)
    s.add(floor)
    s.add(box(24.6, 0.02, 1.6, mat('#CBD3DF'), 0, 0.011, AISLE, false))          // aisle runner
    s.add(box(9.4, 0.02, 6.4, mat('#E9DFCF'), 6.6, 0.011, 4.6, false))            // lounge rug
    // back and left walls, kept low so the floor stays visible
    s.add(box(24.6, 2.6, 0.2, wall, 0, 1.3, -8.3))
    s.add(box(0.2, 2.6, 16.6, wall, -12.3, 1.3, 0))
    for (let x = -10; x <= 0; x += 3.4) {                                         // windows on the back wall
      s.add(box(2.4, 1.3, 0.05, mat('#BFDBFE', { emissive: '#93C5FD', emissiveIntensity: 0.35 }), x, 1.6, -8.18, false))
    }

    // desks
    DESKS.forEach((d, i) => {
      const [x, z] = d.pos
      const dir = d.face === 0 ? 1 : -1          // which way the person faces
      const deskZ = z + dir * 0.85
      s.add(box(1.9, 0.07, 0.9, white, x, 0.74, deskZ))
      for (const lx of [-0.85, 0.85]) s.add(box(0.06, 0.72, 0.8, steel, x + lx, 0.36, deskZ))
      const screen = mat('#0F172A', { emissive: '#60A5FA', emissiveIntensity: 0.5 })
      this.screens.push(screen)
      s.add(box(0.75, 0.45, 0.04, screen, x, 1.12, deskZ + dir * 0.2))
      s.add(box(0.08, 0.2, 0.08, dark, x, 0.86, deskZ + dir * 0.2))
      s.add(box(0.5, 0.02, 0.17, dark, x, 0.785, deskZ - dir * 0.18, false))      // keyboard
      this.chair(x, z, d.face)
      if (i % 3 === 0) s.add(box(0.3, 0.32, 0.22, wood, x + 0.7, 0.93, deskZ, true)) // a stack of files
    })
    // low divider between the two desk rows and the lounge side
    s.add(box(0.12, 1.1, 5.4, wall, 0.6, 0.55, -5.4))

    // meeting room: glass on two sides, table, wall screen
    const glass = new THREE.MeshStandardMaterial({ color: '#BAE6FD', transparent: true, opacity: 0.22, roughness: 0.1 })
    s.add(box(0.06, 2.3, 5.4, glass, 2.3, 1.15, -5.5, false))
    s.add(box(1.2, 2.3, 0.06, glass, 2.9, 1.15, -2.8, false))
    s.add(box(6.6, 2.3, 0.06, glass, 8.0, 1.15, -2.8, false))
    s.add(box(9.2, 0.06, 0.1, steel, 6.9, 2.3, -2.8, false))
    s.add(box(3.6, 0.08, 1.4, wood, 6.8, 0.74, -5.2))
    s.add(box(0.5, 0.72, 0.5, dark, 6.8, 0.36, -5.2))
    s.add(box(2.6, 1.3, 0.06, mat('#0F172A', { emissive: '#38BDF8', emissiveIntensity: 0.35 }), 6.8, 1.6, -8.15, false))
    MEETING.forEach((m) => this.chair(m.pos[0], m.pos[1], m.face))

    // lounge: pool table
    const cloth = mat('#1F7A4D'), rim = mat('#6B4423')
    s.add(box(TABLE.w + 0.3, 0.16, TABLE.d + 0.3, rim, TABLE.x, TABLE.y - 0.1, TABLE.z))
    s.add(box(TABLE.w, 0.04, TABLE.d, cloth, TABLE.x, TABLE.y - 0.01, TABLE.z, false))
    for (const dx of [-1, 1]) for (const dz of [-1, 1]) s.add(box(0.14, 0.7, 0.14, rim, TABLE.x + dx * 1.3, 0.35, TABLE.z + dz * 0.62))
    const ballColors = ['#DC2626', '#F59E0B', '#2563EB', '#7C3AED', '#111827']
    const ballGeo = new THREE.SphereGeometry(0.055, 14, 12)
    ballColors.forEach((c, i) => {
      const mesh = new THREE.Mesh(ballGeo, mat(c, { roughness: 0.3 }))
      mesh.position.set(TABLE.x + 0.5 + (i % 3) * 0.13, TABLE.y + 0.065, TABLE.z - 0.14 + Math.floor(i / 3) * 0.14 + (i % 2) * 0.07)
      mesh.castShadow = true
      s.add(mesh)
      this.balls.push({ mesh, v: new THREE.Vector2() })
    })
    this.cueBall = new THREE.Mesh(ballGeo, mat('#FFFFFF', { roughness: 0.3 }))
    this.cueBall.position.set(TABLE.x - 0.8, TABLE.y + 0.065, TABLE.z)
    this.cueBall.castShadow = true
    s.add(this.cueBall)

    // coffee counter and sofa
    s.add(box(0.7, 0.95, 2.4, white, 11.6, 0.475, 1.6))
    s.add(box(0.35, 0.45, 0.35, dark, 11.6, 1.17, 1.4))
    for (let i = 0; i < 3; i++) s.add(box(0.09, 0.1, 0.09, white, 11.5, 1.0, 2.1 + i * 0.16, false))
    const sofa = mat('#334155')
    s.add(box(0.9, 0.42, 2.8, sofa, 10.75, 0.21, 5.9))
    s.add(box(0.25, 0.75, 2.8, sofa, 11.3, 0.6, 5.9))
    s.add(box(0.9, 0.2, 0.25, sofa, 10.75, 0.52, 4.6))
    s.add(box(0.9, 0.2, 0.25, sofa, 10.75, 0.52, 7.2))
    s.add(box(0.8, 0.06, 0.8, wood, 9.1, 0.36, 7.7))                               // side table

    // plants
    for (const [x, z] of [[-11.4, -7.4], [1.6, -7.4], [11.4, 3.6], [3.0, 7.4], [-11.4, 7.4]] as const) {
      s.add(box(0.5, 0.5, 0.5, pot, x, 0.25, z))
      const leaves = new THREE.Mesh(new THREE.IcosahedronGeometry(0.55, 0), plantGreen)
      leaves.position.set(x, 1.05, z)
      leaves.castShadow = true
      s.add(leaves)
    }
  }

  private chair(x: number, z: number, face: number) {
    const g = new THREE.Group()
    const m = mat('#475569')
    g.add(box(0.5, 0.07, 0.5, m, 0, 0.46, 0), box(0.5, 0.55, 0.07, m, 0, 0.78, -0.24), box(0.07, 0.44, 0.07, mat('#94A3B8'), 0, 0.22, 0))
    g.position.set(x, 0, z)
    g.rotation.y = face
    this.scene.add(g)
  }

  // ---------- who does what ----------

  private startPhase() {
    const phase = PHASES[this.phaseIndex].name
    // a built assistant with work waiting stays at the desk; the rest are free to move
    const busy = (p: Person) => p.info.built && this.pending > 0
    const free = this.people.filter((p) => !busy(p))
    const send = (p: Person, spot: Spot, goal: string) => {
      p.next = spot
      p.goal = goal
      p.leaveAt = this.t + rand(0, 4.5)      // nobody gets up at exactly the same moment
    }
    const desk = (p: Person) => DESKS[this.people.indexOf(p) % DESKS.length]

    if (phase === 'work') {
      this.people.forEach((p) => send(p, desk(p), 'Heading back to the desk'))
    } else if (phase === 'meeting') {
      const going = pick(free, Math.min(free.length, 4 + Math.round(Math.random())))
      const seats = pick(MEETING, going.length)
      going.forEach((p, i) => send(p, seats[i], 'Heading to a meeting'))
      this.speakerAt = 0
    } else {
      const order = pick(free, free.length)
      const plan: [Spot, string][] = [
        ...POOL.map((sp): [Spot, string] => [sp, 'Off to the pool table']),
        [COFFEE[0], 'Off to get a coffee'],
        ...pick(SOFA, 1).map((sp): [Spot, string] => [sp, 'Taking a break']),
      ]
      order.slice(0, plan.length).forEach((p, i) => send(p, plan[i][0], plan[i][1]))
      this.shotAt = this.t + 7
    }
  }

  private direct() {
    const t = this.t
    if (t >= this.phaseEnds) {
      this.phaseIndex = (this.phaseIndex + 1) % PHASES.length
      this.phaseEnds = t + PHASES[this.phaseIndex].seconds + rand(-2, 3)
      this.startPhase()
    }
    for (const p of this.people) {
      if (p.next && t >= p.leaveAt) {
        p.goTo(p.next, p.goal)
        p.next = null
      }
    }

    // meeting: one person talks at a time, the others turn to look
    const seated = this.people.filter((p) => p.pose === 'sit')
    if (seated.length && t >= this.speakerAt) {
      const current = seated.find((p) => p.speaking)
      const others = seated.filter((p) => p !== current)
      seated.forEach((p) => (p.speaking = false))
      const speaker = (others.length ? pick(others, 1) : seated)[0]
      speaker.speaking = true
      this.speakerAt = t + rand(3.5, 7)
    }
    const speaker = seated.find((p) => p.speaking)
    for (const p of this.people) {
      if (p.pose !== 'sit') p.speaking = false
      p.lookAt = p.pose === 'sit' && speaker && p !== speaker ? speaker.root.position
        : p.pose === 'pool' ? this.cueBall.position : null
    }

    // pool: players take turns; a good shot gets a reaction from whoever is watching
    const players = this.people.filter((p) => p.pose === 'pool')
    if (players.length && t >= this.shotAt) {
      const shooter = players[this.shooter++ % players.length]
      shooter.aimUntil = t + 1.6
      this.shotAt = t + rand(4.5, 7)
      window.setTimeout(() => !this.disposed && this.strike(players, shooter), 1600)
    }
  }

  private strike(players: Person[], shooter: Person) {
    const target = pick(this.balls, 1)[0]
    this.cueTarget = target.mesh.position.clone()
    const dir = new THREE.Vector2(target.mesh.position.x - this.cueBall.position.x, target.mesh.position.z - this.cueBall.position.z)
    if (dir.length() < 0.01) dir.set(1, 0)
    target.v.copy(dir.normalize().rotateAround(new THREE.Vector2(), rand(-0.5, 0.5)).multiplyScalar(rand(1.6, 2.6)))
    if (Math.random() < 0.6) {
      for (const p of players) if (p !== shooter && Math.random() < 0.7) p.cheerUntil = this.t + rand(0.9, 1.3) + 0.5
    }
  }

  private rollBalls(dt: number) {
    if (this.cueTarget) {
      const p = this.cueBall.position
      const to = new THREE.Vector3(this.cueTarget.x, p.y, this.cueTarget.z)
      if (p.distanceTo(to) < 0.13) this.cueTarget = null
      else p.lerp(to, Math.min(1, dt * 6))
    }
    const halfW = TABLE.w / 2 - 0.07, halfD = TABLE.d / 2 - 0.07
    for (const b of [...this.balls, { mesh: this.cueBall, v: new THREE.Vector2() }]) {
      const p = b.mesh.position
      p.x += b.v.x * dt
      p.z += b.v.y * dt
      if (Math.abs(p.x - TABLE.x) > halfW) { p.x = TABLE.x + Math.sign(p.x - TABLE.x) * halfW; b.v.x *= -0.8 }
      if (Math.abs(p.z - TABLE.z) > halfD) { p.z = TABLE.z + Math.sign(p.z - TABLE.z) * halfD; b.v.y *= -0.8 }
      b.v.multiplyScalar(Math.max(0, 1 - dt * 1.1))
    }
  }

  private report() {
    const out: Status = {}
    for (const p of this.people) {
      if (p.pose === 'walk') out[p.info.key] = p.goal
      else if (p.pose === 'sit') out[p.info.key] = p.speaking ? 'Presenting in the meeting' : 'In a meeting'
      else if (p.pose === 'pool') out[p.info.key] = this.t < p.aimUntil ? 'Lining up a shot' : 'Playing pool'
      else if (p.pose === 'coffee') out[p.info.key] = 'Coffee break'
      else if (p.pose === 'sofa') out[p.info.key] = 'Relaxing on the sofa'
      else if (!p.info.built) out[p.info.key] = 'At the desk, getting set up'
      else out[p.info.key] = this.pending > 0
        ? `Working: ${this.pending} ${this.pending === 1 ? 'entry is' : 'entries are'} waiting for your approval`
        : 'At the desk, books are up to date'
    }
    const key = JSON.stringify(out)
    if (key !== this.lastStatus) {
      this.lastStatus = key
      this.onStatus(out)
    }
  }

  // ---------- public controls ----------

  /** How many suggestions from built assistants are waiting. Clearing them gets a small celebration. */
  setPending(n: number) {
    if (n === 0 && this.pending > 0) {
      for (const p of this.people) if (p.info.built) { p.cheerUntil = this.t + 1.4; if (p.pose === 'type') p.stretchAt = this.t }
    }
    if (n > 0 && this.pending === 0) {
      // new work arrived: built assistants drop what they are doing and go back to their desks
      this.people.forEach((p, i) => {
        if (p.info.built) { p.next = DESKS[i % DESKS.length]; p.goal = 'New work came in, back to the desk'; p.leaveAt = this.t + 0.4 }
      })
    }
    this.pending = n
  }

  setPaused(paused: boolean) {
    this.paused = paused
    this.clock.getDelta()
  }

  rotate(by: number) {
    this.angle = THREE.MathUtils.clamp(this.angle + by, -1.2, 1.2)
    this.placeCamera()
    if (this.paused) this.renderer.render(this.scene, this.camera)
  }

  resize() {
    const w = this.canvas.clientWidth || 300, h = this.canvas.clientHeight || 200
    this.renderer.setSize(w, h, false)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.placeCamera()
    if (this.paused) this.renderer.render(this.scene, this.camera)
  }

  private placeCamera() {
    // far enough back that the whole floor fits, whether the view is wide or tall
    const vfov = THREE.MathUtils.degToRad(this.camera.fov)
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * this.camera.aspect)
    const dist = Math.max(12.4 / Math.tan(hfov / 2), 9.6 / Math.tan(vfov / 2))
    const tilt = 0.8
    this.camera.position.set(Math.sin(this.angle) * Math.cos(tilt) * dist, Math.sin(tilt) * dist, Math.cos(this.angle) * Math.cos(tilt) * dist)
    this.camera.lookAt(0, 0.4, 1.0)
  }

  private frame(dt = 0) {
    this.t += dt
    this.direct()
    for (const p of this.people) p.update(this.t, dt)
    this.rollBalls(dt)
    this.screens.forEach((m, i) => (m.emissiveIntensity = 0.45 + Math.sin(this.t * 2.3 + i) * 0.08))
    this.report()
    this.renderer.render(this.scene, this.camera)
  }

  private loop() {
    if (this.disposed) return
    this.raf = requestAnimationFrame(this.loop)
    const dt = Math.min(this.clock.getDelta(), 0.1)
    if (!this.paused) this.frame(dt)
  }

  private onVisibility = () => { this.clock.getDelta() }

  dispose() {
    this.disposed = true
    cancelAnimationFrame(this.raf)
    document.removeEventListener('visibilitychange', this.onVisibility)
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh
      m.geometry?.dispose()
      const mats = Array.isArray(m.material) ? m.material : m.material ? [m.material] : []
      for (const x of mats) {
        (x as THREE.SpriteMaterial).map?.dispose()
        x.dispose()
      }
    })
    this.renderer.dispose()
  }
}
