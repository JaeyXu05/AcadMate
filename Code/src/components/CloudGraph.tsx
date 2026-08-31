import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { CloudGraphProps, CloudNode } from '../types/cloud';
import { createGalaxyDust, createNebulaDust } from '../utils/galaxyBackground';

function seededRandom(seed: number) {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let result = value;
    result = Math.imul(result ^ (result >>> 15), result | 1);
    result ^= result + Math.imul(result ^ (result >>> 7), result | 61);
    return ((result ^ (result >>> 14)) >>> 0) / 4294967296;
  };
}

function makeGlowTexture(inner: string, mid: string): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas 2D context unavailable');
  const gradient = context.createRadialGradient(64, 64, 0, 64, 64, 64);
  gradient.addColorStop(0, inner);
  gradient.addColorStop(0.28, mid);
  gradient.addColorStop(1, 'rgba(0,0,0,0)');
  context.fillStyle = gradient;
  context.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeDomainLabelTexture(label: string, color: string): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 128;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas 2D context unavailable');
  context.fillStyle = 'rgba(7, 12, 27, 0.82)';
  context.beginPath();
  context.roundRect(8, 16, 496, 96, 26);
  context.fill();
  context.strokeStyle = color;
  context.lineWidth = 4;
  context.stroke();
  context.font = '600 42px system-ui, sans-serif';
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillStyle = '#f6f8ff';
  context.fillText(label, 256, 64, 450);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  return texture;
}

function makeSelectedLabelTexture(node: CloudNode): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 1024;
  canvas.height = 256;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas 2D context unavailable');
  const accent = node.color ?? '#8ba8ff';
  const gradient = context.createLinearGradient(20, 24, 1004, 232);
  gradient.addColorStop(0, 'rgba(8, 15, 34, 0.96)');
  gradient.addColorStop(1, 'rgba(14, 25, 54, 0.9)');
  context.fillStyle = gradient;
  context.beginPath();
  context.roundRect(18, 22, 988, 212, 48);
  context.fill();
  context.strokeStyle = accent;
  context.lineWidth = 7;
  context.stroke();
  context.fillStyle = accent;
  context.beginPath();
  context.arc(84, 94, 14, 0, Math.PI * 2);
  context.fill();
  context.textAlign = 'left';
  context.textBaseline = 'middle';
  context.fillStyle = '#f8faff';
  context.font = '700 66px system-ui, sans-serif';
  context.fillText(node.name || '未命名导师', 122, 92, 820);
  context.fillStyle = 'rgba(218, 228, 250, 0.76)';
  context.font = '400 34px system-ui, sans-serif';
  context.fillText(`${node.department || '院系待补充'} · ${node.domain_name || '待分类'}`, 68, 170, 875);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  return texture;
}

function compactNodeLabel(value: string): string[] {
  const compact = value.replace(/^中国科学技术大学/, '').trim() || value;
  const characters = Array.from(compact);
  if (characters.length <= 11) return [compact];
  const split = Math.ceil(characters.length / 2);
  return [characters.slice(0, split).join(''), characters.slice(split).join('')];
}

function makeNodeLabelTexture(label: string): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 640;
  canvas.height = 224;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas 2D context unavailable');
  const lines = compactNodeLabel(label).slice(0, 2);
  const gradient = context.createLinearGradient(18, 16, 622, 208);
  gradient.addColorStop(0, 'rgba(6, 14, 32, 0.92)');
  gradient.addColorStop(1, 'rgba(12, 28, 58, 0.78)');
  context.fillStyle = gradient;
  context.beginPath();
  context.roundRect(14, 18, 612, 188, 42);
  context.fill();
  context.strokeStyle = 'rgba(126, 192, 255, 0.72)';
  context.lineWidth = 5;
  context.stroke();
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillStyle = '#f3f8ff';
  context.font = lines.length === 1 ? '600 43px system-ui, sans-serif' : '600 37px system-ui, sans-serif';
  lines.forEach((line, index) => {
    const y = lines.length === 1 ? 112 : 80 + index * 66;
    context.fillText(line, 320, y, 550);
  });
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  return texture;
}

function makeMentorLabelTexture(node: CloudNode): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 480;
  canvas.height = 128;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas 2D context unavailable');
  const accent = node.color ?? '#8ba8ff';
  context.fillStyle = 'rgba(6, 12, 27, 0.82)';
  context.beginPath();
  context.roundRect(8, 14, 464, 100, 28);
  context.fill();
  context.strokeStyle = accent;
  context.lineWidth = 3;
  context.stroke();
  context.fillStyle = accent;
  context.beginPath();
  context.arc(46, 64, 8, 0, Math.PI * 2);
  context.fill();
  context.textAlign = 'left';
  context.textBaseline = 'middle';
  context.fillStyle = '#f5f8ff';
  context.font = '600 37px system-ui, sans-serif';
  context.fillText(node.name || '未命名导师', 70, 64, 370);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  return texture;
}

/**
 * 姓名常驻标签做空间抽样，而不是按论文数排序：论文字段可能缺失，并且
 * 所有导师仍可通过悬停、搜索和点击获得完整姓名。这样既不制造学术排名，
 * 也避免大院系里几十块姓名牌彼此覆盖。
 */
function pickMentorLabelNodes(nodes: CloudNode[]): CloudNode[] {
  const limit = Math.min(18, Math.max(8, Math.ceil(Math.sqrt(nodes.length) * 2.4)));
  const byStableVisualWeight = [...nodes].sort((left, right) => (
    (right.size ?? 1) - (left.size ?? 1)
    || (right.lum ?? 0.7) - (left.lum ?? 0.7)
    || left.id.localeCompare(right.id)
  ));
  const picked: CloudNode[] = [];
  for (const candidate of byStableVisualWeight) {
    const separated = picked.every((node) => Math.hypot(
      (node.x ?? 0) - (candidate.x ?? 0),
      (node.y ?? 0) - (candidate.y ?? 0),
      (node.z ?? 0) - (candidate.z ?? 0),
    ) >= 56);
    if (separated) picked.push(candidate);
    if (picked.length >= limit) break;
  }
  return picked;
}

function nodeColor(node: CloudNode): THREE.Color {
  const color = new THREE.Color();
  try {
    color.set(node.color ?? '#7d9cff');
  } catch {
    color.set('#7d9cff');
  }
  return color;
}

export default function CloudGraph({
  nodes,
  edges,
  selectedId,
  onSelectNode,
  onHoverNode,
  loading,
  focusRequest,
  resetSignal,
  reducedMotion,
  labelMode = 'domains',
  initialTarget,
  className,
  style,
}: CloudGraphProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const pointerGlowRef = useRef<HTMLDivElement>(null);
  const hoverRef = useRef<HTMLDivElement>(null);
  const hoverNameRef = useRef<HTMLDivElement>(null);
  const hoverDeptRef = useRef<HTMLDivElement>(null);
  const hoverDomainRef = useRef<HTMLDivElement>(null);
  const selectedRef = useRef(selectedId);
  const onSelectRef = useRef(onSelectNode);
  const onHoverRef = useRef(onHoverNode);
  const applySelectionRef = useRef<() => void>(() => undefined);
  const focusNodeRef = useRef<(id: string) => void>(() => undefined);
  const resetViewRef = useRef<() => void>(() => undefined);
  const targetX = initialTarget?.[0] ?? 0;
  const targetY = initialTarget?.[1] ?? 0;
  const targetZ = initialTarget?.[2] ?? 0;

  selectedRef.current = selectedId;
  onSelectRef.current = onSelectNode;
  onHoverRef.current = onHoverNode;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || nodes.length === 0) return;

    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const shouldReduceMotion = reducedMotion ?? mediaQuery.matches;
    const sceneTarget = new THREE.Vector3(targetX, targetY, targetZ);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#030611');
    scene.fog = new THREE.FogExp2('#030611', 0.00042);

    const maxRadius = Math.max(420, ...nodes.map((node) => Math.hypot(
      (node.x ?? 0) - targetX,
      (node.y ?? 0) - targetY,
      (node.z ?? 0) - targetZ,
    )));
    const cameraRadius = Math.max(900, maxRadius * 1.72);
    const camera = new THREE.PerspectiveCamera(48, mount.clientWidth / Math.max(1, mount.clientHeight), 0.1, 7000);
    // The department overview is intentionally close to face-on: every department
    // lives on the same plane and should read as an equal peer, without perspective
    // making the far half of the orbit look smaller or less important.
    const makeDefaultCameraPosition = (aspect: number) => {
      const safeAspect = Math.max(0.48, aspect);
      if (labelMode === 'nodes') {
        return sceneTarget.clone().add(new THREE.Vector3(
          0,
          cameraRadius * 1.34 * Math.max(1, 1 / safeAspect),
          cameraRadius * 0.04,
        ));
      }
      const narrowScale = Math.max(1, 1.1 / safeAspect);
      return sceneTarget.clone().add(new THREE.Vector3(
        0,
        cameraRadius * 0.52 * narrowScale,
        cameraRadius * 0.98 * narrowScale,
      ));
    };
    let defaultCameraPosition = makeDefaultCameraPosition(camera.aspect);
    camera.position.copy(defaultCameraPosition);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight, false);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.92;
    renderer.domElement.setAttribute('aria-hidden', 'true');
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(sceneTarget);
    controls.enableDamping = !shouldReduceMotion;
    controls.dampingFactor = 0.065;
    controls.autoRotate = !shouldReduceMotion;
    controls.autoRotateSpeed = 0.28;
    controls.minDistance = 110;
    controls.maxDistance = 4200;
    controls.enablePan = true;
    controls.listenToKeyEvents(mount);
    controls.saveState();

    const disposableTextures = new Set<THREE.Texture>();

    // 多层背景由旋臂、环带和星晕共同组成。误差函数有界且种子固定，
    // 因此不会呈现完美数学曲线，也不会在刷新时重新跳位。
    const armGeometry = new THREE.BufferGeometry();
    const fineGalaxy = createGalaxyDust(14500, 107, 'fine');
    armGeometry.setAttribute('position', new THREE.BufferAttribute(fineGalaxy.positions, 3));
    armGeometry.setAttribute('color', new THREE.BufferAttribute(fineGalaxy.colors, 3));
    const armMaterial = new THREE.PointsMaterial({
      size: 1.4,
      vertexColors: true,
      transparent: true,
      opacity: 0.68,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const armDust = new THREE.Points(armGeometry, armMaterial);
    armDust.position.copy(sceneTarget);
    scene.add(armDust);

    // 第二层以更宽的误差和大颗粒低透明雾连接彩色旋臂与不完整环带。
    const armMistGeometry = new THREE.BufferGeometry();
    const mistGalaxy = createGalaxyDust(6200, 401, 'mist');
    armMistGeometry.setAttribute('position', new THREE.BufferAttribute(mistGalaxy.positions, 3));
    armMistGeometry.setAttribute('color', new THREE.BufferAttribute(mistGalaxy.colors, 3));
    const armMistTexture = makeGlowTexture('rgba(255,255,255,0.78)', 'rgba(141,169,255,0.22)');
    disposableTextures.add(armMistTexture);
    const armMistMaterial = new THREE.PointsMaterial({
      size: 7.4,
      vertexColors: true,
      map: armMistTexture,
      transparent: true,
      opacity: 0.18,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const armMist = new THREE.Points(armMistGeometry, armMistMaterial);
    armMist.position.copy(sceneTarget);
    scene.add(armMist);

    // 宽幅碎裂星云呼应参考视频的横向粒子云；它来自独立分布而非旋臂复制。
    const bandGalaxy = createNebulaDust(3600, 781);
    const bandGeometry = new THREE.BufferGeometry();
    bandGeometry.setAttribute('position', new THREE.BufferAttribute(bandGalaxy.positions, 3));
    bandGeometry.setAttribute('color', new THREE.BufferAttribute(bandGalaxy.colors, 3));
    const bandMaterial = new THREE.PointsMaterial({
      size: 10.5,
      vertexColors: true,
      map: armMistTexture,
      transparent: true,
      opacity: 0.12,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const bandDust = new THREE.Points(bandGeometry, bandMaterial);
    bandDust.position.copy(sceneTarget);
    scene.add(bandDust);

    // 两层球幕星野围绕相机与银河：细星提供真实密度，大星只作少量冷暖节奏。
    // 使用固定种子和静态缓冲，不在逐帧创建对象，也不会与导师数据混淆。
    const deepRandom = seededRandom(1138);
    const farStarCount = 5200;
    const farStarPositions = new Float32Array(farStarCount * 3);
    const farStarColors = new Float32Array(farStarCount * 3);
    const starPalette = ['#c9dcff', '#8fb6ff', '#e5efff', '#b7a8ff', '#f4d9bd'].map((value) => new THREE.Color(value));
    for (let index = 0; index < farStarCount; index += 1) {
      const radius = 1350 + deepRandom() * 2250;
      const theta = deepRandom() * Math.PI * 2;
      const vertical = deepRandom() * 2 - 1;
      const planar = Math.sqrt(Math.max(0, 1 - vertical * vertical));
      farStarPositions[index * 3] = radius * planar * Math.cos(theta);
      farStarPositions[index * 3 + 1] = radius * vertical * 0.72;
      farStarPositions[index * 3 + 2] = radius * planar * Math.sin(theta);
      const color = starPalette[Math.floor(deepRandom() * starPalette.length)];
      const strength = 0.48 + deepRandom() * 0.52;
      farStarColors[index * 3] = color.r * strength;
      farStarColors[index * 3 + 1] = color.g * strength;
      farStarColors[index * 3 + 2] = color.b * strength;
    }
    const farStarGeometry = new THREE.BufferGeometry();
    farStarGeometry.setAttribute('position', new THREE.BufferAttribute(farStarPositions, 3));
    farStarGeometry.setAttribute('color', new THREE.BufferAttribute(farStarColors, 3));
    const farStarMaterial = new THREE.PointsMaterial({
      size: 1,
      sizeAttenuation: false,
      vertexColors: true,
      transparent: true,
      opacity: 0.64,
      depthWrite: false,
      depthTest: false,
      fog: false,
      blending: THREE.AdditiveBlending,
    });
    const farStars = new THREE.Points(farStarGeometry, farStarMaterial);
    farStars.position.copy(sceneTarget);
    farStars.renderOrder = -10;
    scene.add(farStars);

    const beaconCount = 460;
    const beaconPositions = new Float32Array(beaconCount * 3);
    for (let index = 0; index < beaconCount; index += 1) {
      const radius = 1000 + deepRandom() * 2500;
      const theta = deepRandom() * Math.PI * 2;
      const vertical = deepRandom() * 2 - 1;
      const planar = Math.sqrt(Math.max(0, 1 - vertical * vertical));
      beaconPositions[index * 3] = radius * planar * Math.cos(theta);
      beaconPositions[index * 3 + 1] = radius * vertical * 0.7;
      beaconPositions[index * 3 + 2] = radius * planar * Math.sin(theta);
    }
    const beaconTexture = makeGlowTexture('rgba(255,255,255,0.92)', 'rgba(119,159,255,0.25)');
    disposableTextures.add(beaconTexture);
    const beaconGeometry = new THREE.BufferGeometry();
    beaconGeometry.setAttribute('position', new THREE.BufferAttribute(beaconPositions, 3));
    const beaconMaterial = new THREE.PointsMaterial({
      size: 3.8,
      sizeAttenuation: false,
      color: '#9ebeff',
      map: beaconTexture,
      transparent: true,
      opacity: 0.38,
      alphaTest: 0.01,
      depthWrite: false,
      depthTest: false,
      fog: false,
      blending: THREE.AdditiveBlending,
    });
    const beaconStars = new THREE.Points(beaconGeometry, beaconMaterial);
    beaconStars.position.copy(sceneTarget);
    beaconStars.renderOrder = -9;
    scene.add(beaconStars);

    // 大尺度低透明星云让黑色背景有冷暖层次；保持在数据和旋臂之后，避免抢夺语义色。
    const nebulaGroup = new THREE.Group();
    const addNebula = (
      position: [number, number, number],
      scale: [number, number],
      inner: string,
      mid: string,
      color: string,
      opacity: number,
    ) => {
      const texture = makeGlowTexture(inner, mid);
      disposableTextures.add(texture);
      const material = new THREE.SpriteMaterial({
        map: texture,
        color,
        transparent: true,
        opacity,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
      });
      const sprite = new THREE.Sprite(material);
      sprite.position.set(...position);
      sprite.scale.set(scale[0], scale[1], 1);
      sprite.renderOrder = -8;
      nebulaGroup.add(sprite);
    };
    addNebula([-520, -70, 120], [760, 390], 'rgba(98,184,255,0.52)', 'rgba(59,88,210,0.15)', '#6a8fff', 0.15);
    addNebula([470, -40, -150], [720, 420], 'rgba(176,118,255,0.48)', 'rgba(95,61,190,0.13)', '#9f79ff', 0.13);
    addNebula([40, -110, 520], [620, 300], 'rgba(79,231,216,0.42)', 'rgba(35,122,174,0.12)', '#5ed8d1', 0.1);
    nebulaGroup.position.copy(sceneTarget);
    scene.add(nebulaGroup);

    // 总览使用接近圆形的青蓝涡核，导师层在倾斜视角下使用椭圆盘面。
    const overviewCore = labelMode === 'nodes';
    const coreGroup = new THREE.Group();
    const addCoreLayer = (
      inner: string,
      mid: string,
      color: string,
      opacity: number,
      width: number,
      height: number,
    ) => {
      const texture = makeGlowTexture(inner, mid);
      disposableTextures.add(texture);
      const material = new THREE.SpriteMaterial({
        map: texture,
        color,
        transparent: true,
        opacity,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      const sprite = new THREE.Sprite(material);
      sprite.scale.set(width, height, 1);
      coreGroup.add(sprite);
    };
    addCoreLayer(
      'rgba(146,236,255,0.66)', 'rgba(55,92,218,0.18)', '#72a9ff', 0.38,
      overviewCore ? 310 : 440, overviewCore ? 310 : 188,
    );
    addCoreLayer(
      'rgba(204,248,255,0.94)', 'rgba(69,156,255,0.3)', '#a2e6ff', 0.56,
      overviewCore ? 146 : 230, overviewCore ? 146 : 96,
    );
    addCoreLayer(
      'rgba(255,255,255,1)', 'rgba(137,224,255,0.5)', '#f5ffff', 0.74,
      overviewCore ? 42 : 62, overviewCore ? 42 : 26,
    );
    coreGroup.position.copy(sceneTarget);
    scene.add(coreGroup);

    // 光池跟随鼠标投射到银河盘，给背景和节点提供局部明暗响应。
    const cursorGlowTexture = makeGlowTexture('rgba(183,211,255,0.48)', 'rgba(76,112,214,0.12)');
    disposableTextures.add(cursorGlowTexture);
    const cursorGlowMaterial = new THREE.SpriteMaterial({
      map: cursorGlowTexture,
      color: '#9fc0ff',
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const cursorGlow = new THREE.Sprite(cursorGlowMaterial);
    cursorGlow.scale.set(310, 190, 1);
    cursorGlow.visible = false;
    scene.add(cursorGlow);

    // Base relationship layer: same-field nearest neighbours, not co-authorship.
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const edgePositions: number[] = [];
    const edgeColors: number[] = [];
    for (const edge of edges) {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      if (!source || !target) continue;
      edgePositions.push(source.x ?? 0, source.y ?? 0, source.z ?? 0, target.x ?? 0, target.y ?? 0, target.z ?? 0);
      const sourceColor = nodeColor(source);
      const targetColor = nodeColor(target);
      edgeColors.push(sourceColor.r, sourceColor.g, sourceColor.b, targetColor.r, targetColor.g, targetColor.b);
    }
    const edgeGeometry = new THREE.BufferGeometry();
    edgeGeometry.setAttribute('position', new THREE.Float32BufferAttribute(edgePositions, 3));
    edgeGeometry.setAttribute('color', new THREE.Float32BufferAttribute(edgeColors, 3));
    const edgeMaterial = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.16,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const edgeLines = new THREE.LineSegments(edgeGeometry, edgeMaterial);
    scene.add(edgeLines);

    const selectedEdgeGeometry = new THREE.BufferGeometry();
    const selectedEdgeMaterial = new THREE.LineBasicMaterial({
      color: '#edf4ff',
      transparent: true,
      opacity: 0.82,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const selectedEdgeLines = new THREE.LineSegments(selectedEdgeGeometry, selectedEdgeMaterial);
    selectedEdgeLines.renderOrder = 4;
    scene.add(selectedEdgeLines);

    // Domain labels at semantic cluster centroids; labels carry meaning in addition to color.
    const domainGroups = new Map<string, { name: string; color: string; nodes: CloudNode[] }>();
    for (const node of nodes) {
      const group = domainGroups.get(node.domain ?? 'unclassified') ?? {
        name: node.domain_name ?? '待分类',
        color: node.color ?? '#a7b0c0',
        nodes: [],
      };
      group.nodes.push(node);
      domainGroups.set(node.domain ?? 'unclassified', group);
    }
    const domainLabels: THREE.Sprite[] = [];
    if (labelMode === 'domains') for (const group of domainGroups.values()) {
      const center = group.nodes.reduce(
        (sum, node) => sum.add(new THREE.Vector3(node.x ?? 0, node.y ?? 0, node.z ?? 0)),
        new THREE.Vector3(),
      ).divideScalar(group.nodes.length);
      const texture = makeDomainLabelTexture(group.name, group.color);
      disposableTextures.add(texture);
      const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        opacity: 0.72,
        depthWrite: false,
        depthTest: false,
      });
      const label = new THREE.Sprite(material);
      label.position.copy(center).add(new THREE.Vector3(0, 42, 0));
      label.scale.set(88, 22, 1);
      label.renderOrder = 5;
      domainLabels.push(label);
      scene.add(label);
    }

    const nodeLabels: THREE.Sprite[] = [];
    const labelNodes = labelMode === 'nodes'
      ? nodes
      : labelMode === 'mentors' ? pickMentorLabelNodes(nodes) : [];
    for (const node of labelNodes) {
      const isMentorLabel = labelMode === 'mentors';
      const texture = isMentorLabel ? makeMentorLabelTexture(node) : makeNodeLabelTexture(node.name);
      disposableTextures.add(texture);
      const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        opacity: isMentorLabel ? 0.82 : 0.9,
        depthWrite: false,
        depthTest: false,
      });
      const label = new THREE.Sprite(material);
      label.position.set(node.x ?? 0, (node.y ?? 0) + (isMentorLabel ? 25 : 42), node.z ?? 0);
      label.scale.set(isMentorLabel ? 64 : 102, isMentorLabel ? 17 : 35.7, 1);
      label.renderOrder = 6;
      nodeLabels.push(label);
      scene.add(label);
    }

    // 选中导师拥有独立的场景内姓名标牌；放大后无需把视线移到侧栏才能确认对象。
    const selectedLabelMaterial = new THREE.SpriteMaterial({
      transparent: true,
      opacity: 0.96,
      depthWrite: false,
      depthTest: false,
    });
    const selectedLabel = new THREE.Sprite(selectedLabelMaterial);
    selectedLabel.scale.set(112, 28, 1);
    selectedLabel.renderOrder = 7;
    selectedLabel.visible = false;
    scene.add(selectedLabel);
    let selectedLabelTexture: THREE.CanvasTexture | null = null;

    // One instanced GPU draw for all mentor nodes.
    const count = nodes.length;
    const starGeometry = new THREE.InstancedBufferGeometry();
    starGeometry.setAttribute('position', new THREE.Float32BufferAttribute([
      -1, -1, 0, 1, -1, 0, 1, 1, 0,
      1, 1, 0, -1, 1, 0, -1, -1, 0,
    ], 3));
    starGeometry.setAttribute('uv', new THREE.Float32BufferAttribute([
      0, 0, 1, 0, 1, 1,
      1, 1, 0, 1, 0, 0,
    ], 2));
    const instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3);
    const instanceSize = new THREE.InstancedBufferAttribute(new Float32Array(count), 1);
    const instanceLum = new THREE.InstancedBufferAttribute(new Float32Array(count), 1);
    const instanceCenter = new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3);
    const instanceEmphasis = new THREE.InstancedBufferAttribute(new Float32Array(count), 1);
    starGeometry.setAttribute('aColor', instanceColor);
    starGeometry.setAttribute('aSize', instanceSize);
    starGeometry.setAttribute('aLum', instanceLum);
    starGeometry.setAttribute('aCenter', instanceCenter);
    starGeometry.setAttribute('aEmphasis', instanceEmphasis);

    const originalColors: THREE.Color[] = [];
    const baseSizes = new Float32Array(count);
    nodes.forEach((node, index) => {
      const color = nodeColor(node);
      originalColors.push(color);
      instanceColor.setXYZ(index, color.r, color.g, color.b);
      const size = Math.max(10, (node.size ?? 1.2) * (0.9 + 0.55 * (node.lum ?? 0.8)) * 6.2);
      baseSizes[index] = size;
      instanceSize.setX(index, size);
      instanceLum.setX(index, node.lum ?? 0.75);
      // This attribute is the shader's actual position source. The former code never populated it.
      instanceCenter.setXYZ(index, node.x ?? 0, node.y ?? 0, node.z ?? 0);
      instanceEmphasis.setX(index, 1);
    });

    const starMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uPixelRatio: { value: Math.min(window.devicePixelRatio, 2) },
        uMotion: { value: shouldReduceMotion ? 0 : 1 },
        uPointer: { value: new THREE.Vector2(-10, -10) },
        uResolution: { value: new THREE.Vector2(renderer.domElement.width, renderer.domElement.height) },
      },
      vertexShader: /* glsl */ `
        attribute vec3 aColor;
        attribute float aSize;
        attribute float aLum;
        attribute vec3 aCenter;
        attribute float aEmphasis;
        varying vec3 vColor;
        varying float vLum;
        varying float vPulse;
        varying float vEmphasis;
        varying vec2 vUv;
        uniform float uTime;
        uniform float uPixelRatio;
        uniform float uMotion;
        void main() {
          vColor = aColor;
          vLum = aLum;
          vUv = uv;
          vEmphasis = aEmphasis;
          vPulse = mix(1.0, 0.9 + 0.1 * sin(uTime * 1.15 + float(gl_InstanceID) * 0.53), uMotion);
          vec4 centerView = modelViewMatrix * vec4(aCenter, 1.0);
          float halfSize = 0.5 * aSize * uPixelRatio;
          centerView.xy += (uv - vec2(0.5)) * halfSize;
          gl_Position = projectionMatrix * centerView;
        }
      `,
      fragmentShader: /* glsl */ `
        varying vec3 vColor;
        varying float vLum;
        varying float vPulse;
        varying float vEmphasis;
        varying vec2 vUv;
        uniform vec2 uPointer;
        uniform vec2 uResolution;
        void main() {
          float distanceFromCenter = length(vUv - vec2(0.5)) * 2.0;
          float halo = smoothstep(1.0, 0.08, distanceFromCenter);
          float core = smoothstep(0.42, 0.0, distanceFromCenter);
          vec2 screenUv = gl_FragCoord.xy / max(uResolution, vec2(1.0));
          float pointerLight = 1.0 - smoothstep(0.02, 0.22, distance(screenUv, uPointer));
          float alpha = (halo * 0.76 + core * 0.62) * vLum * vPulse * vEmphasis * (1.0 + pointerLight * 0.48);
          vec3 color = vColor * (0.72 + core * 0.68) + vec3(0.22) * core + vec3(0.1, 0.14, 0.24) * pointerLight;
          if (alpha < 0.012) discard;
          gl_FragColor = vec4(color, alpha);
        }
      `,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const stars = new THREE.InstancedMesh(starGeometry, starMaterial, count);
    stars.frustumCulled = false;
    scene.add(stars);

    let animationFrame = 0;
    let pointerFrame = 0;
    let isIntersecting = true;
    let lastFrame = 0;
    let cameraTween: {
      start: number;
      duration: number;
      fromPosition: THREE.Vector3;
      controlPosition: THREE.Vector3;
      toPosition: THREE.Vector3;
      fromTarget: THREE.Vector3;
      toTarget: THREE.Vector3;
      fromFov: number;
      toFov: number;
    } | null = null;
    const pointerNdcTarget = new THREE.Vector2();
    const pointerNdcCurrent = new THREE.Vector2();
    const cursorGlowTarget = new THREE.Vector3();
    let cursorGlowActive = false;

    const renderOnce = (time = performance.now()) => {
      starMaterial.uniforms.uTime.value = time * 0.001;
      renderer.render(scene, camera);
    };

    const scheduleFrame = () => {
      if (!animationFrame && isIntersecting && !document.hidden) {
        animationFrame = requestAnimationFrame(animate);
      }
    };

    function animate(time: number) {
      animationFrame = 0;
      if (!isIntersecting || document.hidden) return;
      if (time - lastFrame < 1000 / 45) {
        scheduleFrame();
        return;
      }
      const deltaSeconds = lastFrame ? Math.min(0.05, (time - lastFrame) / 1000) : 0;
      lastFrame = time;

      if (cameraTween) {
        const progress = Math.min(1, (time - cameraTween.start) / cameraTween.duration);
        const eased = progress < 0.5
          ? 4 * progress * progress * progress
          : 1 - Math.pow(-2 * progress + 2, 3) / 2;
        const inverse = 1 - eased;
        camera.position.set(
          inverse * inverse * cameraTween.fromPosition.x + 2 * inverse * eased * cameraTween.controlPosition.x + eased * eased * cameraTween.toPosition.x,
          inverse * inverse * cameraTween.fromPosition.y + 2 * inverse * eased * cameraTween.controlPosition.y + eased * eased * cameraTween.toPosition.y,
          inverse * inverse * cameraTween.fromPosition.z + 2 * inverse * eased * cameraTween.controlPosition.z + eased * eased * cameraTween.toPosition.z,
        );
        controls.target.lerpVectors(cameraTween.fromTarget, cameraTween.toTarget, eased);
        camera.fov = THREE.MathUtils.lerp(cameraTween.fromFov, cameraTween.toFov, eased);
        camera.updateProjectionMatrix();
        if (progress >= 1) cameraTween = null;
      }
      if (!shouldReduceMotion) {
        pointerNdcCurrent.lerp(pointerNdcTarget, 0.075);
        coreGroup.position.set(
          targetX + pointerNdcCurrent.x * 7,
          targetY + pointerNdcCurrent.y * 2.5,
          targetZ - pointerNdcCurrent.x * 4,
        );
        armDust.rotation.x = pointerNdcCurrent.y * 0.006;
        armMist.rotation.x = pointerNdcCurrent.y * 0.004;
        if (cursorGlowActive) cursorGlow.position.lerp(cursorGlowTarget, 0.14);
      }
      controls.update(deltaSeconds);
      armDust.rotation.y = time * 0.0000025;
      armMist.rotation.y = -time * 0.0000015;
      renderOnce(time);
      if (!shouldReduceMotion || cameraTween) scheduleFrame();
    }

    const updateSelectedEdges = (selected: string | undefined) => {
      const positions: number[] = [];
      if (selected) {
        for (const edge of edges) {
          if (edge.source !== selected && edge.target !== selected) continue;
          const source = nodeById.get(edge.source);
          const target = nodeById.get(edge.target);
          if (!source || !target) continue;
          positions.push(source.x ?? 0, source.y ?? 0, source.z ?? 0, target.x ?? 0, target.y ?? 0, target.z ?? 0);
        }
      }
      selectedEdgeGeometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      selectedEdgeGeometry.computeBoundingSphere();
    };

    applySelectionRef.current = () => {
      const selected = selectedRef.current;
      const neighbours = new Set<string>();
      if (selected) {
        for (const edge of edges) {
          if (edge.source === selected) neighbours.add(edge.target);
          if (edge.target === selected) neighbours.add(edge.source);
        }
      }
      nodes.forEach((node, index) => {
        const isSelected = node.id === selected;
        const isNeighbour = neighbours.has(node.id);
        const color = originalColors[index];
        if (isSelected) {
          instanceColor.setXYZ(index, 1, 1, 1);
          instanceSize.setX(index, baseSizes[index] * 1.65);
          instanceLum.setX(index, 1);
          instanceEmphasis.setX(index, 1);
        } else {
          instanceColor.setXYZ(index, color.r, color.g, color.b);
          instanceSize.setX(index, baseSizes[index] * (isNeighbour ? 1.18 : 1));
          instanceLum.setX(index, node.lum ?? 0.75);
          instanceEmphasis.setX(index, selected ? (isNeighbour ? 0.9 : 0.16) : 1);
        }
      });
      instanceColor.needsUpdate = true;
      instanceSize.needsUpdate = true;
      instanceLum.needsUpdate = true;
      instanceEmphasis.needsUpdate = true;
      edgeMaterial.opacity = selected ? 0.045 : 0.16;
      domainLabels.forEach((label) => {
        label.visible = !selected;
      });
      nodeLabels.forEach((label) => {
        label.visible = !selected;
      });
      const selectedNode = selected ? nodeById.get(selected) : undefined;
      selectedLabelTexture?.dispose();
      selectedLabelTexture = null;
      selectedLabelMaterial.map = null;
      selectedLabel.visible = false;
      if (selectedNode) {
        if (hoverRef.current) hoverRef.current.style.display = 'none';
        selectedLabelTexture = makeSelectedLabelTexture(selectedNode);
        selectedLabelMaterial.map = selectedLabelTexture;
        selectedLabelMaterial.needsUpdate = true;
        selectedLabel.position.set(
          selectedNode.x ?? 0,
          (selectedNode.y ?? 0) + 44,
          selectedNode.z ?? 0,
        );
        selectedLabel.visible = true;
      }
      updateSelectedEdges(selected);
      renderOnce();
    };

    focusNodeRef.current = (id: string) => {
      const node = nodeById.get(id);
      if (!node) return;
      const target = new THREE.Vector3(node.x ?? 0, node.y ?? 0, node.z ?? 0);
      const direction = camera.position.clone().sub(controls.target);
      if (direction.lengthSq() < 0.001) direction.set(0, 0.5, 1);
      direction.normalize();
      const destination = target.clone().add(direction.clone().multiplyScalar(360));
      controls.autoRotate = false;
      if (shouldReduceMotion) {
        camera.position.copy(destination);
        controls.target.copy(target);
        camera.fov = 43;
        camera.updateProjectionMatrix();
        controls.update();
        renderOnce();
      } else {
        const side = direction.clone().cross(new THREE.Vector3(0, 1, 0));
        if (side.lengthSq() < 0.001) side.set(1, 0, 0);
        side.normalize().multiplyScalar(54);
        const controlPosition = camera.position.clone().lerp(destination, 0.48).add(side).add(new THREE.Vector3(0, 42, 0));
        cameraTween = {
          start: performance.now(),
          duration: 880,
          fromPosition: camera.position.clone(),
          controlPosition,
          toPosition: destination,
          fromTarget: controls.target.clone(),
          toTarget: target,
          fromFov: camera.fov,
          toFov: 43,
        };
        scheduleFrame();
      }
    };

    resetViewRef.current = () => {
      cameraTween = null;
      camera.position.copy(defaultCameraPosition);
      controls.target.copy(sceneTarget);
      camera.fov = 48;
      camera.updateProjectionMatrix();
      controls.autoRotate = !shouldReduceMotion;
      controls.update();
      renderOnce();
      if (!shouldReduceMotion) scheduleFrame();
    };

    applySelectionRef.current();

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const temporaryPoint = new THREE.Vector3();
    const cursorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -targetY);
    const pickNode = (clientX: number, clientY: number): number | null => {
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.x = ((clientX - bounds.left) / bounds.width) * 2 - 1;
      pointer.y = -((clientY - bounds.top) / bounds.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      let bestIndex: number | null = null;
      let bestDistanceSquared = Number.POSITIVE_INFINITY;
      for (let index = 0; index < nodes.length; index += 1) {
        const node = nodes[index];
        temporaryPoint.set(node.x ?? 0, node.y ?? 0, node.z ?? 0);
        const distanceSquared = raycaster.ray.distanceSqToPoint(temporaryPoint);
        if (distanceSquared < bestDistanceSquared) {
          bestDistanceSquared = distanceSquared;
          bestIndex = index;
        }
      }
      // Department labels are the primary overview controls, so their hit target is
      // deliberately much larger than a mentor star's precise selection radius.
      const threshold = labelMode === 'nodes'
        ? Math.max(52, camera.position.distanceTo(controls.target) * 0.026)
        : Math.max(15, camera.position.distanceTo(controls.target) * 0.012);
      return bestIndex !== null && bestDistanceSquared <= threshold * threshold ? bestIndex : null;
    };

    const hideHover = () => {
      if (pointerFrame) {
        cancelAnimationFrame(pointerFrame);
        pointerFrame = 0;
      }
      if (hoverRef.current) hoverRef.current.style.display = 'none';
      if (pointerGlowRef.current) pointerGlowRef.current.style.opacity = '0';
      starMaterial.uniforms.uPointer.value.set(-10, -10);
      pointerNdcTarget.set(0, 0);
      cursorGlowActive = false;
      cursorGlow.visible = false;
      onHoverRef.current?.(null);
      renderOnce();
    };

    let hoveredId: string | null = null;
    let pointerPosition = { x: 0, y: 0 };
    const updateHover = () => {
      pointerFrame = 0;
      const index = pickNode(pointerPosition.x, pointerPosition.y);
      if (pointerGlowRef.current && !shouldReduceMotion) {
        const bounds = renderer.domElement.getBoundingClientRect();
        pointerGlowRef.current.style.opacity = '1';
        pointerGlowRef.current.style.transform = `translate3d(${pointerPosition.x - bounds.left - 190}px, ${pointerPosition.y - bounds.top - 190}px, 0)`;
      }
      const intersection = raycaster.ray.intersectPlane(cursorPlane, cursorGlowTarget);
      cursorGlowActive = Boolean(intersection && cursorGlowTarget.length() < 900);
      cursorGlow.visible = cursorGlowActive;
      if (cursorGlowActive) {
        cursorGlowTarget.y = 4;
        if (shouldReduceMotion) cursorGlow.position.copy(cursorGlowTarget);
      }
      if (selectedRef.current) {
        if (hoverRef.current) hoverRef.current.style.display = 'none';
        if (shouldReduceMotion) renderOnce();
        return;
      }
      const node = index === null ? undefined : nodes[index];
      if (!node) {
        renderer.domElement.style.cursor = 'grab';
        if (hoveredId !== null) {
          hoveredId = null;
          hideHover();
        }
        return;
      }
      renderer.domElement.style.cursor = 'pointer';
      if (hoveredId !== node.id) {
        hoveredId = node.id;
        onHoverRef.current?.(node.id);
      }
      if (hoverNameRef.current) hoverNameRef.current.textContent = node.name;
      if (hoverDeptRef.current) hoverDeptRef.current.textContent = node.department || '院系待补充';
      if (hoverDomainRef.current) hoverDomainRef.current.textContent = node.domain_name || '待分类';
      if (hoverRef.current) {
        hoverRef.current.style.display = 'block';
        hoverRef.current.style.left = `${Math.min(pointerPosition.x + 16, window.innerWidth - 248)}px`;
        hoverRef.current.style.top = `${Math.min(pointerPosition.y + 12, window.innerHeight - 112)}px`;
      }
      if (shouldReduceMotion) renderOnce();
    };

    const onPointerMove = (event: PointerEvent) => {
      pointerPosition = { x: event.clientX, y: event.clientY };
      const bounds = renderer.domElement.getBoundingClientRect();
      const normalizedX = (event.clientX - bounds.left) / Math.max(1, bounds.width);
      const normalizedY = (event.clientY - bounds.top) / Math.max(1, bounds.height);
      starMaterial.uniforms.uPointer.value.set(normalizedX, 1 - normalizedY);
      pointerNdcTarget.set(normalizedX * 2 - 1, -(normalizedY * 2 - 1));
      if (!pointerFrame) pointerFrame = requestAnimationFrame(updateHover);
    };
    let pointerDown = { x: 0, y: 0 };
    const onPointerDown = (event: PointerEvent) => {
      pointerDown = { x: event.clientX, y: event.clientY };
    };
    const onClick = (event: MouseEvent) => {
      if (Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y) > 5) return;
      const index = pickNode(event.clientX, event.clientY);
      hideHover();
      onSelectRef.current?.(index === null ? null : nodes[index].id);
    };
    renderer.domElement.addEventListener('pointermove', onPointerMove);
    renderer.domElement.addEventListener('pointerdown', onPointerDown);
    renderer.domElement.addEventListener('pointerleave', hideHover);
    renderer.domElement.addEventListener('click', onClick);

    const onResize = () => {
      const width = mount.clientWidth;
      const height = mount.clientHeight;
      if (!width || !height) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      defaultCameraPosition = makeDefaultCameraPosition(camera.aspect);
      if (!selectedRef.current) {
        camera.position.copy(defaultCameraPosition);
        controls.target.copy(sceneTarget);
        controls.update();
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width, height, false);
      starMaterial.uniforms.uPixelRatio.value = Math.min(window.devicePixelRatio, 2);
      starMaterial.uniforms.uResolution.value.set(renderer.domElement.width, renderer.domElement.height);
      renderOnce();
    };
    const resizeObserver = new ResizeObserver(onResize);
    resizeObserver.observe(mount);
    const intersectionObserver = new IntersectionObserver(([entry]) => {
      isIntersecting = entry.isIntersecting;
      if (isIntersecting) scheduleFrame();
      else if (animationFrame) cancelAnimationFrame(animationFrame);
    });
    intersectionObserver.observe(mount);
    const onVisibilityChange = () => {
      if (document.hidden && animationFrame) cancelAnimationFrame(animationFrame);
      else scheduleFrame();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    const onControlsChange = () => renderOnce();
    controls.addEventListener('change', onControlsChange);
    scheduleFrame();

    return () => {
      cancelAnimationFrame(animationFrame);
      cancelAnimationFrame(pointerFrame);
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      document.removeEventListener('visibilitychange', onVisibilityChange);
      renderer.domElement.removeEventListener('pointermove', onPointerMove);
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      renderer.domElement.removeEventListener('pointerleave', hideHover);
      renderer.domElement.removeEventListener('click', onClick);
      controls.removeEventListener('change', onControlsChange);
      controls.stopListenToKeyEvents();
      controls.dispose();
      selectedLabelTexture?.dispose();
      scene.traverse((object) => {
        const renderable = object as THREE.Object3D & {
          geometry?: THREE.BufferGeometry;
          material?: THREE.Material | THREE.Material[];
        };
        renderable.geometry?.dispose();
        if (Array.isArray(renderable.material)) renderable.material.forEach((material) => material.dispose());
        else renderable.material?.dispose();
      });
      disposableTextures.forEach((texture) => texture.dispose());
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      applySelectionRef.current = () => undefined;
      focusNodeRef.current = () => undefined;
      resetViewRef.current = () => undefined;
    };
  }, [edges, nodes, reducedMotion, labelMode, targetX, targetY, targetZ]);

  useEffect(() => {
    applySelectionRef.current();
  }, [selectedId]);

  useEffect(() => {
    if (focusRequest) focusNodeRef.current(focusRequest.id);
  }, [focusRequest]);

  useEffect(() => {
    if (resetSignal !== undefined) resetViewRef.current();
  }, [resetSignal]);

  return (
    <div
      ref={mountRef}
      className={className}
      role="img"
      aria-label={labelMode === 'nodes'
        ? `三维院系导航星图，共 ${nodes.length} 个院系，等权双环排列。可拖拽旋转、滚轮缩放，方向键平移。`
        : `三维导师研究星图，共 ${nodes.length} 位导师。可拖拽旋转、滚轮缩放，方向键平移。`}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Escape') onSelectRef.current?.(null);
        if (event.key === '0') resetViewRef.current();
      }}
      style={{
        position: 'absolute',
        inset: 0,
        overflow: 'hidden',
        background: 'radial-gradient(ellipse at 50% 44%, rgba(26, 52, 112, 0.3) 0%, rgba(7, 15, 39, 0.48) 38%, #02040c 76%)',
        outline: 'none',
        ...style,
      }}
    >
      <div
        ref={pointerGlowRef}
        aria-hidden="true"
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          zIndex: 2,
          width: 380,
          height: 380,
          borderRadius: '50%',
          pointerEvents: 'none',
          opacity: 0,
          background: 'radial-gradient(circle, rgba(122, 158, 255, 0.13) 0%, rgba(72, 111, 213, 0.055) 42%, rgba(20, 39, 89, 0) 72%)',
          mixBlendMode: 'screen',
          willChange: 'transform, opacity',
          transition: 'opacity 180ms ease-out',
        }}
      />
      <div
        ref={hoverRef}
        aria-hidden="true"
        style={{
          display: 'none',
          position: 'fixed',
          zIndex: 40,
          width: 228,
          pointerEvents: 'none',
          background: 'rgba(7, 12, 27, 0.94)',
          border: '1px solid rgba(159, 181, 236, 0.28)',
          borderRadius: 12,
          padding: '10px 12px',
          color: '#f7f9ff',
          boxShadow: '0 12px 34px rgba(0, 0, 0, 0.42)',
          backdropFilter: 'blur(14px)',
        }}
      >
        <div ref={hoverNameRef} style={{ fontSize: 14, fontWeight: 650, lineHeight: 1.4 }} />
        <div ref={hoverDeptRef} style={{ marginTop: 3, color: 'rgba(224, 231, 249, 0.66)', fontSize: 12 }} />
        <div ref={hoverDomainRef} style={{ marginTop: 7, color: '#a9c0ff', fontSize: 12 }} />
      </div>
      {loading && (
        <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: '#c8d5f4' }}>
          正在建立研究星图…
        </div>
      )}
    </div>
  );
}
