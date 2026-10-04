import { expect, it } from 'vitest';
import * as THREE from 'three';
import { GlobeStaticBatch } from './globeStaticBatch';

it('batches opaque outlines without changing transparent cap order, picking or ownership', () => {
  const scene = new THREE.Scene();
  const sources: any[] = [];
  for (let i = 0; i < 12; i++) {
    const parent = new THREE.Group();
    parent.__globeObjType = 'polygon';
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ color: '#ffaa00', transparent: true, opacity: .2 }));
    mesh.position.x = i * 2;
    mesh.geometry.clearGroups();
    const line = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), new THREE.LineBasicMaterial({ color: '#626970' }));
    line.geometry.translate(i * 2, 0, 0);
    parent.add(mesh, line); scene.add(parent); sources.push(mesh, line);
  }
  const batch = new GlobeStaticBatch();
  expect(batch.rebuild(scene)).toEqual({ objects: 12, batches: 1 });
  expect(sources.filter(object => object.isLineSegments).every(object => !object.visible)).toBe(true);
  expect(sources.filter(object => object.isMesh).every(object => object.visible)).toBe(true);
  const strokes = scene.children.at(-1).children.find((object: any) => object.isLineSegments);
  expect(strokes.geometry.attributes.position.count).toBe(12 * 8);
  const ray = new THREE.Raycaster(new THREE.Vector3(0, 0, 3), new THREE.Vector3(0, 0, -1));
  expect(ray.intersectObjects(scene.children, true).some((hit: any) => hit.object === sources[0])).toBe(true);
  batch.clear();
  expect(sources.every(object => object.visible && object.matrixAutoUpdate)).toBe(true);
  expect(scene.children).toHaveLength(12);
  expect(batch.rebuild(scene)).toEqual({ objects: 12, batches: 1 });
  batch.clear();
});
