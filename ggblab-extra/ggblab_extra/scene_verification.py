"""
Scene Verification Infrastructure for ggblab

This module provides reusable components for verifying geometric constructions
across all chapters of textbook-2025.

Usage:
    from ggblab_extra.scene_verification import SceneVerifier, ScenePlayback
    
    verifier = SceneVerifier(ggb, parser)
    results = await verifier.verify_all()
    
    playback = ScenePlayback(ggb, construction_df)
    await playback.play_layer(1)
    await playback.play_all_layers()
"""

import asyncio
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass
from enum import Enum
import polars as pl
import networkx as nx


class ObjectType(Enum):
    """GeoGebra object types."""
    POINT = "point"
    LINE = "line"
    SEGMENT = "segment"
    RAY = "ray"
    CIRCLE = "circle"
    POLYGON = "polygon"
    ANGLE = "angle"
    DISTANCE = "distance"
    AREA = "area"
    BOOLEAN = "boolean"
    NUMBER = "number"
    TEXT = "text"
    UNKNOWN = "unknown"


@dataclass
class VerificationResult:
    """Result of a single object verification."""
    object_name: str
    object_type: str
    valid: bool
    error: Optional[str] = None
    value: Optional[Any] = None
    details: Optional[Dict] = None


class SceneVerifier:
    """
    Multi-level verification for geometric constructions.
    
    Implements type-specific validators for each GeoGebra object type,
    with progressive verification from basic existence checks to
    geometric property assertions.
    
    Example:
        verifier = SceneVerifier(ggb, parser)
        results = await verifier.verify_all()
        print(verifier.summary(results))
    """
    
    def __init__(self, ggb: 'GeoGebra', parser: 'ggb_parser'):
        """
        Initialize verifier.
        
        Args:
            ggb: Active GeoGebra instance
            parser: Parsed construction with dependency graph
        """
        self.ggb = ggb
        self.parser = parser
        self.df = parser.df
    
    async def verify_all(self) -> Dict[str, VerificationResult]:
        """
        Verify all objects in construction.
        
        Returns:
            Dictionary mapping object name to VerificationResult
        """
        results = {}
        
        for row in self.df.iter_rows(named=True):
            obj_name = row['Name']
            obj_type = row['Type']
            
            try:
                result = await self._verify_by_type(obj_name, obj_type)
                results[obj_name] = result
            except Exception as e:
                results[obj_name] = VerificationResult(
                    object_name=obj_name,
                    object_type=obj_type,
                    valid=False,
                    error=str(e)
                )
        
        return results
    
    async def _verify_by_type(self, obj_name: str, obj_type: str) -> VerificationResult:
        """
        Route to type-specific validator.
        """
        validators = {
            'point': self._verify_point,
            'line': self._verify_line,
            'segment': self._verify_segment,
            'circle': self._verify_circle,
            'polygon': self._verify_polygon,
            'angle': self._verify_angle,
            'distance': self._verify_distance,
            'area': self._verify_area,
            'boolean': self._verify_boolean,
            'number': self._verify_number,
        }
        
        validator = validators.get(obj_type, self._verify_generic)
        return await validator(obj_name)
    
    async def _verify_point(self, obj_name: str) -> VerificationResult:
        """Verify point is defined (not undefined)."""
        try:
            x = await self.ggb.function("getXcoord", [obj_name])
            y = await self.ggb.function("getYcoord", [obj_name])
            
            valid = x is not None and y is not None
            value = (float(x), float(y)) if valid else None
            
            return VerificationResult(
                object_name=obj_name,
                object_type='point',
                valid=valid,
                value=value
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='point',
                valid=False,
                error=str(e)
            )
    
    async def _verify_line(self, obj_name: str) -> VerificationResult:
        """Verify line equation is valid."""
        try:
            value = await self.ggb.function("getValueString", [obj_name])
            valid = value is not None and value.strip() != ""
            
            return VerificationResult(
                object_name=obj_name,
                object_type='line',
                valid=valid,
                value=value
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='line',
                valid=False,
                error=str(e)
            )
    
    async def _verify_segment(self, obj_name: str) -> VerificationResult:
        """Verify segment has positive length."""
        try:
            length = await self.ggb.function("getValueString", [obj_name])
            valid = float(length) > 0 if length else False
            
            return VerificationResult(
                object_name=obj_name,
                object_type='segment',
                valid=valid,
                value=length
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='segment',
                valid=False,
                error=str(e)
            )
    
    async def _verify_circle(self, obj_name: str) -> VerificationResult:
        """Verify circle equation is valid."""
        try:
            value = await self.ggb.function("getValueString", [obj_name])
            valid = value is not None and value.strip() != ""
            
            return VerificationResult(
                object_name=obj_name,
                object_type='circle',
                valid=valid,
                value=value
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='circle',
                valid=False,
                error=str(e)
            )
    
    async def _verify_polygon(self, obj_name: str) -> VerificationResult:
        """Verify polygon area is positive."""
        try:
            area = await self.ggb.function("getValueString", [obj_name])
            valid = float(area) > 0 if area else False
            
            return VerificationResult(
                object_name=obj_name,
                object_type='polygon',
                valid=valid,
                value=area
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='polygon',
                valid=False,
                error=str(e)
            )
    
    async def _verify_angle(self, obj_name: str) -> VerificationResult:
        """Verify angle is in valid range [0, 360] degrees."""
        try:
            value = await self.ggb.function("getValueString", [obj_name])
            angle = float(value) if value else None
            valid = angle is not None and 0 <= angle <= 360
            
            return VerificationResult(
                object_name=obj_name,
                object_type='angle',
                valid=valid,
                value=angle
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='angle',
                valid=False,
                error=str(e)
            )
    
    async def _verify_distance(self, obj_name: str) -> VerificationResult:
        """Verify distance is non-negative."""
        try:
            value = await self.ggb.function("getValueString", [obj_name])
            distance = float(value) if value else None
            valid = distance is not None and distance >= 0
            
            return VerificationResult(
                object_name=obj_name,
                object_type='distance',
                valid=valid,
                value=distance
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='distance',
                valid=False,
                error=str(e)
            )
    
    async def _verify_area(self, obj_name: str) -> VerificationResult:
        """Verify area is positive."""
        try:
            value = await self.ggb.function("getValueString", [obj_name])
            area = float(value) if value else None
            valid = area is not None and area > 0
            
            return VerificationResult(
                object_name=obj_name,
                object_type='area',
                valid=valid,
                value=area
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='area',
                valid=False,
                error=str(e)
            )
    
    async def _verify_boolean(self, obj_name: str) -> VerificationResult:
        """Verify boolean value (true/false)."""
        try:
            value = await self.ggb.function("getValueString", [obj_name])
            is_true = str(value).lower() == 'true'
            
            return VerificationResult(
                object_name=obj_name,
                object_type='boolean',
                valid=is_true,
                value=is_true
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='boolean',
                valid=False,
                error=str(e)
            )
    
    async def _verify_number(self, obj_name: str) -> VerificationResult:
        """Verify number is defined (not null)."""
        try:
            value = await self.ggb.function("getValueString", [obj_name])
            is_defined = value is not None and value.strip() != ""
            num_value = float(value) if is_defined else None
            
            return VerificationResult(
                object_name=obj_name,
                object_type='number',
                valid=is_defined,
                value=num_value
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='number',
                valid=False,
                error=str(e)
            )
    
    async def _verify_generic(self, obj_name: str) -> VerificationResult:
        """Generic verification: object exists and has value."""
        try:
            value = await self.ggb.function("getValueString", [obj_name])
            valid = value is not None
            
            return VerificationResult(
                object_name=obj_name,
                object_type='unknown',
                valid=valid,
                value=value
            )
        except Exception as e:
            return VerificationResult(
                object_name=obj_name,
                object_type='unknown',
                valid=False,
                error=str(e)
            )
    
    def summary(self, results: Dict[str, VerificationResult]) -> str:
        """Generate human-readable summary of verification results."""
        total = len(results)
        passed = sum(1 for r in results.values() if r.valid)
        failed = total - passed
        
        summary_lines = [
            f"Verification Summary",
            f"{'='*50}",
            f"Total objects: {total}",
            f"Passed: {passed} ✓",
            f"Failed: {failed} ✗",
            f"Pass rate: {100*passed/total:.1f}%",
        ]
        
        if failed > 0:
            summary_lines.append(f"\nFailed objects:")
            for name, result in results.items():
                if not result.valid:
                    summary_lines.append(f"  - {name} ({result.object_type}): {result.error}")
        
        return "\n".join(summary_lines)


class ScenePlayback:
    """
    Layer-by-layer playback of geometric constructions.
    
    Enables step-wise execution of construction protocols for educational
    visualization and exploration.
    
    Example:
        playback = ScenePlayback(ggb, construction_df)
        await playback.play_layer(0)
        await playback.play_layer(1)
        # Or play all:
        await playback.play_all_layers()
    """
    
    def __init__(self, ggb: 'GeoGebra', construction_df: pl.DataFrame):
        """
        Initialize playback.
        
        Args:
            ggb: Active GeoGebra instance
            construction_df: DataFrame with construction protocol
        """
        self.ggb = ggb
        self.df = construction_df
        self.current_layer = -1
        self.executed_objects = set()
    
    async def play_layer(self, layer: int, pause_sec: float = 1.0) -> List[str]:
        """
        Execute all commands at a given layer.
        
        Args:
            layer: Layer number to execute
            pause_sec: Pause duration after layer execution
            
        Returns:
            List of object names created in this layer
        """
        layer_objects = self.df.filter(pl.col('Layer') == layer)
        created = []
        
        for row in layer_objects.iter_rows(named=True):
            obj_name = row['Name']
            command = row['Command']
            
            # Skip free objects (no command) and already executed
            if not command or obj_name in self.executed_objects:
                continue
            
            try:
                await self.ggb.command(f"{obj_name} = {command}")
                self.executed_objects.add(obj_name)
                created.append(obj_name)
                print(f"  ✓ {obj_name} ({row['Type']})")
            except Exception as e:
                print(f"  ✗ {obj_name}: {str(e)}")
        
        self.current_layer = layer
        await asyncio.sleep(pause_sec)
        
        return created
    
    async def play_all_layers(self, pause_sec: float = 1.0) -> None:
        """
        Sequentially execute all layers.
        
        Args:
            pause_sec: Pause duration between layers
        """
        layers = sorted(set(self.df['Layer']))
        
        for layer in layers:
            print(f"\n→ Layer {layer}")
            await self.play_layer(layer, pause_sec)
    
    async def reset(self) -> None:
        """Clear construction and reset playback state."""
        await self.ggb.command("DeleteAll[]")
        self.current_layer = -1
        self.executed_objects.clear()
        print("Construction reset.")
    
    async def highlight_layer(self, layer: int, highlight: bool = True) -> None:
        """
        Visually highlight objects in a layer.
        
        Args:
            layer: Layer to highlight
            highlight: True to highlight, False to unhighlight
        """
        layer_objects = self.df.filter(pl.col('Layer') == layer)
        
        for row in layer_objects.iter_rows(named=True):
            obj_name = row['Name']
            try:
                await self.ggb.function("setLineThickness", [obj_name, 5 if highlight else 1])
            except:
                pass  # Some objects may not support styling


# Example usage template
EXAMPLE_USAGE = '''
# Initialize GeoGebra and load construction
from ggblab import GeoGebra, ggb_file
from ggblab_extra import ggb_parser
from ggblab_extra.scene_verification import SceneVerifier, ScenePlayback

ggb = await GeoGebra().init()

# Load construction (e.g., Thales' theorem)
f = ggb_file()
f.load("chapters/01/scenes/thales.ggb")
await ggb.function("evalXML", [f.geogebra_xml])

# Build construction protocol dataframe
construction_data = {}
for obj in await ggb.function("getAllObjectNames"):
    info = await ggb.function(
        ["getObjectType", "getCommandString", "getValueString", "getCaption", "getLayer"],
        [obj]
    )
    construction_data[obj] = info

import polars as pl
df = pl.DataFrame({
    'Name': list(construction_data.keys()),
    'Type': [v[0] for v in construction_data.values()],
    'Command': [v[1] for v in construction_data.values()],
    'Value': [v[2] for v in construction_data.values()],
    'Caption': [v[3] for v in construction_data.values()],
    'Layer': [v[4] for v in construction_data.values()],
}, strict=False)

# Parse dependencies
parser = ggb_parser()
parser.initialize_dataframe(df=df)
parser.parse()

# Verify construction
verifier = SceneVerifier(ggb, parser)
results = await verifier.verify_all()
print(verifier.summary(results))

# Interactive playback
playback = ScenePlayback(ggb, df)
await playback.play_layer(0)  # Free objects
await playback.play_layer(1)  # First derived layer
# ... and so on
'''
