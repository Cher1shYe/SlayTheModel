using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;

if (args.Length is < 2 or > 3)
{
    Console.Error.WriteLine("Usage: Sts2.IlProbe <assembly> <full-type-name> [method-name]");
    return 1;
}

var assemblyPath = Path.GetFullPath(args[0]);
var requestedType = args[1];
var requestedMethod = args.Length == 3 ? args[2] : null;

using var stream = File.OpenRead(assemblyPath);
using var peReader = new PEReader(stream);
var reader = peReader.GetMetadataReader();
var opcodes = OpcodeTable.Create();

var typeHandle = reader.TypeDefinitions.FirstOrDefault(handle => FullTypeName(reader, handle) == requestedType);
if (typeHandle.IsNil)
{
    Console.Error.WriteLine($"type_not_found={requestedType}");
    return 2;
}

var type = reader.GetTypeDefinition(typeHandle);
var matched = 0;
foreach (var methodHandle in type.GetMethods())
{
    var method = reader.GetMethodDefinition(methodHandle);
    var methodName = reader.GetString(method.Name);
    if (requestedMethod is not null && methodName != requestedMethod)
    {
        continue;
    }

    if (method.RelativeVirtualAddress == 0)
    {
        continue;
    }

    matched++;
    Console.WriteLine($"METHOD {requestedType}::{methodName}");
    var body = peReader.GetMethodBody(method.RelativeVirtualAddress);
    var il = body.GetILBytes()
        ?? throw new BadImageFormatException($"Method {methodName} has no IL body.");
    var offset = 0;
    while (offset < il.Length)
    {
        var instructionOffset = offset;
        var first = il[offset++];
        var value = first == 0xFE
            ? (ushort)(0xFE00 | il[offset++])
            : first;

        if (!opcodes.TryGetValue(value, out var opcode))
        {
            Console.WriteLine($"  IL_{instructionOffset:X4}: <unknown 0x{value:X4}>");
            break;
        }

        var operand = ReadOperand(reader, il, ref offset, opcode.OperandType);
        Console.WriteLine(
            operand is null
                ? $"  IL_{instructionOffset:X4}: {opcode.Name}"
                : $"  IL_{instructionOffset:X4}: {opcode.Name} {operand}");
    }
}

if (matched == 0)
{
    Console.Error.WriteLine($"method_not_found={requestedMethod ?? "<any>"}");
    return 3;
}

return 0;

static string? ReadOperand(
    MetadataReader reader,
    byte[] il,
    ref int offset,
    OperandType operandType)
{
    switch (operandType)
    {
        case OperandType.InlineNone:
            return null;
        case OperandType.ShortInlineI:
            return ((sbyte)il[offset++]).ToString();
        case OperandType.InlineI:
            return ReadInt32(il, ref offset).ToString();
        case OperandType.InlineI8:
            return ReadInt64(il, ref offset).ToString();
        case OperandType.ShortInlineR:
            return ReadSingle(il, ref offset).ToString("R");
        case OperandType.InlineR:
            return ReadDouble(il, ref offset).ToString("R");
        case OperandType.ShortInlineBrTarget:
        {
            var delta = (sbyte)il[offset++];
            return $"IL_{offset + delta:X4}";
        }
        case OperandType.InlineBrTarget:
        {
            var delta = ReadInt32(il, ref offset);
            return $"IL_{offset + delta:X4}";
        }
        case OperandType.ShortInlineVar:
            return il[offset++].ToString();
        case OperandType.InlineVar:
            return ReadUInt16(il, ref offset).ToString();
        case OperandType.InlineString:
        {
            var token = ReadInt32(il, ref offset);
            var handle = MetadataTokens.Handle(token);
            return handle.Kind == HandleKind.UserString
                ? Quote(reader.GetUserString((UserStringHandle)handle))
                : $"token(0x{token:X8})";
        }
        case OperandType.InlineField:
        case OperandType.InlineMethod:
        case OperandType.InlineSig:
        case OperandType.InlineTok:
        case OperandType.InlineType:
        {
            var token = ReadInt32(il, ref offset);
            return FormatToken(reader, token);
        }
        case OperandType.InlineSwitch:
        {
            var count = ReadInt32(il, ref offset);
            var baseOffset = offset + (count * 4);
            var targets = new string[count];
            for (var index = 0; index < count; index++)
            {
                targets[index] = $"IL_{baseOffset + ReadInt32(il, ref offset):X4}";
            }

            return string.Join(", ", targets);
        }
        default:
            throw new NotSupportedException($"Unsupported operand type {operandType}.");
    }
}

static string FormatToken(MetadataReader reader, int token)
{
    var handle = MetadataTokens.Handle(token);
    return handle.Kind switch
    {
        HandleKind.MethodDefinition => reader.GetString(
            reader.GetMethodDefinition((MethodDefinitionHandle)handle).Name),
        HandleKind.MemberReference => reader.GetString(
            reader.GetMemberReference((MemberReferenceHandle)handle).Name),
        HandleKind.FieldDefinition => reader.GetString(
            reader.GetFieldDefinition((FieldDefinitionHandle)handle).Name),
        HandleKind.TypeDefinition => FullTypeName(reader, (TypeDefinitionHandle)handle),
        HandleKind.TypeReference => TypeReferenceName(reader, (TypeReferenceHandle)handle),
        _ => $"{handle.Kind}(0x{token:X8})",
    };
}

static string FullTypeName(MetadataReader reader, TypeDefinitionHandle handle)
{
    var type = reader.GetTypeDefinition(handle);
    var name = reader.GetString(type.Name);
    var declaringType = type.GetDeclaringType();
    if (!declaringType.IsNil)
    {
        return FullTypeName(reader, declaringType) + "+" + name;
    }

    var typeNamespace = reader.GetString(type.Namespace);
    return string.IsNullOrEmpty(typeNamespace) ? name : typeNamespace + "." + name;
}

static string TypeReferenceName(MetadataReader reader, TypeReferenceHandle handle)
{
    var type = reader.GetTypeReference(handle);
    var name = reader.GetString(type.Name);
    var typeNamespace = reader.GetString(type.Namespace);
    return string.IsNullOrEmpty(typeNamespace) ? name : typeNamespace + "." + name;
}

static string Quote(string value) => '"' + value.Replace("\"", "\\\"") + '"';

static ushort ReadUInt16(byte[] bytes, ref int offset)
{
    var value = BitConverter.ToUInt16(bytes, offset);
    offset += 2;
    return value;
}

static int ReadInt32(byte[] bytes, ref int offset)
{
    var value = BitConverter.ToInt32(bytes, offset);
    offset += 4;
    return value;
}

static long ReadInt64(byte[] bytes, ref int offset)
{
    var value = BitConverter.ToInt64(bytes, offset);
    offset += 8;
    return value;
}

static float ReadSingle(byte[] bytes, ref int offset)
{
    var value = BitConverter.ToSingle(bytes, offset);
    offset += 4;
    return value;
}

static double ReadDouble(byte[] bytes, ref int offset)
{
    var value = BitConverter.ToDouble(bytes, offset);
    offset += 8;
    return value;
}

static class OpcodeTable
{
    public static IReadOnlyDictionary<ushort, OpCode> Create()
    {
        var result = new Dictionary<ushort, OpCode>();
        foreach (var field in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
        {
            if (field.GetValue(null) is OpCode opcode)
            {
                result[unchecked((ushort)opcode.Value)] = opcode;
            }
        }

        return result;
    }
}
