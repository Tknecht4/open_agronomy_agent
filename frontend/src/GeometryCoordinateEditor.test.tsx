import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { GeometryCoordinateEditor } from './GeometryCoordinateEditor'
import type { FieldGeometry } from './fieldGeometry'
const outer = [[-113.6,53.3],[-113.59,53.3],[-113.59,53.31],[-113.6,53.3]]
const hole = [[-113.598,53.302],[-113.597,53.302],[-113.597,53.303],[-113.598,53.302]]
function Harness() {
  const [geometry,setGeometry] = useState<FieldGeometry>({kind:'geojson',geojson:{type:'MultiPolygon',coordinates:[[outer,hole],[outer]]},acres:1})
  return <><GeometryCoordinateEditor geometry={geometry} onChange={setGeometry}/><output data-testid="value">{JSON.stringify(geometry)}</output></>
}
describe('keyboard geometry editing',()=>{
  it('changes a named hole vertex without losing another part and supports undo and redo',()=>{
    render(<Harness />)
    fireEvent.click(screen.getByText('Edit coordinates with keyboard'))
    fireEvent.change(screen.getByLabelText('Ring'),{target:{value:'1'}})
    fireEvent.change(screen.getByLabelText('Draft latitude'),{target:{value:'53.3022'}})
    fireEvent.click(screen.getByRole('button',{name:'Update vertex'}))
    const saved=()=>JSON.parse(screen.getByTestId('value').textContent!).geojson.coordinates
    expect(saved()[0][1][0]).toEqual([-113.598,53.3022]); expect(saved()[0][1][3]).toEqual([-113.598,53.3022]);expect(saved()[1][0]).toEqual(outer)
    fireEvent.click(screen.getByRole('button',{name:'Undo coordinate edit'}));expect(saved()[0][1]).toEqual(hole)
    fireEvent.click(screen.getByRole('button',{name:'Redo coordinate edit'}));expect(saved()[0][1][0][1]).toBe(53.3022)
    fireEvent.change(screen.getByLabelText('Draft longitude'),{target:{value:''}})
    fireEvent.click(screen.getByRole('button',{name:'Update vertex'}));expect(screen.getByRole('alert')).toHaveTextContent('Blank is not zero')
    expect(saved()[0][1][0][0]).toBe(-113.598)
  })
})
