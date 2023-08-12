from dataclasses import dataclass
from typing import List
from io import BytesIO
import dataclasses
import struct
import socket
import random
random.seed(1)

TYPE_A = 1
TYPE_NS = 2
CLASS_IN = 1


@dataclass
class DNSHeader:
    id: int
    flags: int
    num_questions: int = 0
    num_answers: int = 0
    num_authorities: int = 0
    num_additionals: int = 0


@dataclass
class DNSQuestion:
    name: bytes  # domain name
    type_: int  # record type
    class_: int


@dataclass
class DNSRecord:
    name: bytes
    type_: int
    class_: int
    ttl: int
    data: bytes  # ip address


@dataclass
class DNSPacket:
    header: DNSHeader
    questions: List[DNSQuestion]
    answers: List[DNSRecord]
    authorities: List[DNSRecord]
    additionals: List[DNSRecord]


def header_to_bytes(header):
    fields = dataclasses.astuple(header)
    # there are 6 `H`s because there are 6 fields
    # `H` represents 2-byte integers
    # `!` is used to represent the order(big, little) being used in computer networking
    return struct.pack('!HHHHHH', *fields)


def question_to_bytes(question):
    return question.name + struct.pack('!HH', question.type_, question.class_)


def encode_dns_name(domain_name):
    encoded = b""
    for part in domain_name.encode("ascii").split(b"."):
        encoded += bytes([len(part)]) + part
    return encoded + b"\x00"


def build_query(domain_name, record_type):
    name = encode_dns_name(domain_name)
    id = random.randint(0, 65535)
    # If this is set then it asks to the DNS resolver (a cache)
    RECURSION_DESIRED = 1 << 8
    header = DNSHeader(id=id, num_questions=1, flags=0)
    question = DNSQuestion(name=name, type_=record_type, class_=CLASS_IN)
    return header_to_bytes(header) + question_to_bytes(question)


def parse_header(reader):
    # Each of the field is 2-byte integer, so 12 bytes to read
    items = struct.unpack('!HHHHHH', reader.read(12))
    return DNSHeader(*items)


def parse_question(reader):
    name = decode_name(reader)
    type_, class_ = struct.unpack('!HH', reader.read(4))
    return DNSQuestion(name, type_, class_)


def parse_record(reader):
    name = decode_name(reader)
    # the the type, class, TTL, and data length together are 10 bytes (2 + 2 + 4 + 2 = 10)
    # so we read 10 bytes
    data = reader.read(10)
    type_, class_, ttl, data_len = struct.unpack('!HHIH', data)

    if type_ == TYPE_NS:
        data = decode_name(reader)
    elif type_ == TYPE_A:
        data = ip_to_string(reader.read(data_len))
    else:
        data = reader.read(data_len)

    return DNSRecord(name, type_, class_, ttl, data)


def decode_name(reader):
    parts = []
    while (length := reader.read(1)[0]) != 0:
        if length & 0b1100_0000:
            parts.append(decode_compressed_name(length, reader))
            break
        else:
            parts.append(reader.read(length))
    return b".".join(parts)


def decode_compressed_name(length, reader):
    pointer_bytes = bytes([length & 0b0011_1111]) + reader.read(1)
    pointer = struct.unpack("!H", pointer_bytes)[0]
    current_pos = reader.tell()
    reader.seek(pointer)
    result = decode_name(reader)
    reader.seek(current_pos)
    return result


def parse_dns_packet(data):
    # BytesIO lets you keep a pointer to the current position in a byte stream
    # and lets you read from it and advance the pointer.
    reader = BytesIO(data)
    header = parse_header(reader)
    questions = [parse_question(reader) for _ in range(header.num_questions)]
    answers = [parse_record(reader) for _ in range(header.num_answers)]
    authorities = [parse_record(reader) for _ in range(header.num_authorities)]
    additionals = [parse_record(reader) for _ in range(header.num_additionals)]

    return DNSPacket(header, questions, answers, authorities, additionals)


def ip_to_string(ip):
    # as an array of 4 numbers in base 10
    return ".".join([str(x) for x in ip])


def send_query(ip_address, domain_name, record_type):
    query = build_query(domain_name, record_type)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(query, (ip_address, 53))

    data, _ = sock.recvfrom(1024)
    return parse_dns_packet(data)


def get_answer(packet: DNSPacket):
    for x in packet.answers:
        if x.type_ == TYPE_A:
            return x.data


def get_nameserver(packet: DNSPacket):
    for x in packet.authorities:
        if x.type_ == TYPE_NS:
            return x.data.decode('utf-8')


def get_nameserver_ip(packet: DNSPacket):
    for x in packet.additionals:
        if x.type_ == TYPE_A:
            return x.data


def resolve(domain_name, record_type):
    NAMESERVER = "198.41.0.4"  # root nameserver's are hardcoded in resolvers
    while True:
        print(f'Querying {NAMESERVER} for {domain_name}')
        response = send_query(NAMESERVER, domain_name, record_type)

        if ip := get_answer(response):
            return ip
        elif nsIP := get_nameserver_ip(response):
            NAMESERVER = nsIP
        # look up the nameserver's IP address if there is one
        elif ns_domain := get_nameserver(response):
            NAMESERVER = resolve(ns_domain, TYPE_A)
        else:
            raise Exception("Something went wrong")


print(resolve('google.com', TYPE_A))
# print(send_query('8.8.8.8', 'yupoo.com', TYPE_A))
